# Integração Home Assistant — Electrolux AC (API oficial Electrolux Group)

**Data:** 2026-07-13
**Status:** Aprovado pelo usuário (design verbal); aguardando revisão do spec escrito
**Objetivo:** Custom component para HAOS que controla ar-condicionado Electrolux via API oficial do portal developer.electrolux.one, com experiência de dispositivo equivalente à integração Midea do usuário (climate + sensores + controles no mesmo device).

## 1. Contexto e fatos da API (extraídos do .har / OpenAPI embutido no portal)

O OpenAPI spec completo foi extraído do bundle JS do portal e está salvo em `openapi.json` na raiz do repositório. Fatos relevantes:

- **Base URL:** `https://api.developer.electrolux.one`
- **Autenticação:** dois headers em toda chamada:
  - `x-api-key: <api_key>`
  - `Authorization: Bearer <accessToken>`
- **Access token:** JWT, expira em 43200 s (12 h). Em `401`, renovar via
  `POST /api/v1/token/refresh` com body `{"refreshToken": "<refreshToken>"}` →
  resposta `{accessToken, refreshToken, expiresIn, tokenType}`. O refresh token é rotacionado — o novo par deve ser persistido.
- **Endpoints usados:**
  - `GET /api/v1/appliances` — lista aparelhos (`applianceId`, `applianceName`, `applianceType`)
  - `GET /api/v1/appliances/{id}/info` — info (marca, modelo) + **capabilities** (dicionário de propriedades com `access`, `type`, `values`, `min`/`max`/`step`)
  - `GET /api/v1/appliances/{id}/state` — estado (`connectionState`, `properties.reported.{...}`)
  - `PUT /api/v1/appliances/{id}/command` — comando JSON, ex. `{"mode": "COOL", "targetTemperatureC": 21}`; respostas 200 OK, 202 "já no estado desejado", 406 "Command validation failed" (ex. aparelho desconectado)
  - `GET /api/v1/configurations/livestream` — retorna `{url, appliances: [{applianceId, properties: [...]}]}` (URL SSE, ex. `https://live.eu.developer.electrolux.one/api/v1/events`)
- **SSE (formato confirmado no SDK oficial `electrolux-oss/electrolux-group-developer-sdk`):**
  - GET na URL do livestream config com os mesmos 2 headers de auth; stream de linhas `data: <json>`
  - Evento: `{"applianceId": "...", "property": "<caminho separado por '/'>", "value": <valor>}`
  - `property == "connectionState"` ou `"connectivityState"` atualiza o estado de conexão; demais propriedades aplicam no caminho dentro de `properties.reported`
  - Reconexão: recriar sessão, backoff fixo de ~10 s; timeout de leitura de 120 s como guarda de keepalive
- **Limites (plano free):** 10 chamadas/s, 5 chamadas concorrentes, **5000 chamadas/dia**, **1 canal SSE concorrente por chave**
- **Erros padronizados:** `developers_0003` (403 forbidden), `developers_0004` (404), `developers_0005` (500), `developers_0006` (406 validação de comando)
- **Capacidades típicas de AC** (exemplo do spec; o aparelho real do usuário é BR e pode variar — tudo é lido dinamicamente):
  `mode` (AUTO/COOL/DRY/FANONLY/OFF), `targetTemperatureC` (min/max/step), `fanSpeedSetting` (AUTO/LOW/MIDDLE/HIGH), `verticalSwing` (ON/OFF), `sleepMode`, `cleanAirMode`, `displayLight` (DISPLAY_LIGHT_0/1), `uiLockMode`, `schedulerMode`, `executeCommand` (ON/OFF — liga/desliga), `applianceState` (OFF/RUNNING), `ambientTemperatureC/F`, `filterState` (GOOD/CLEAN/CHANGE/BUY), `temperatureRepresentation` (CELSIUS/FAHRENHEIT), `networkInterface.linkQualityIndicator`, `alerts`
  - As capabilities incluem `triggers` (regras condicionais, ex. em modo FANONLY a temperatura alvo fica desabilitada) — a v1 **não** interpreta triggers; usa apenas `access`, `values`, `min`/`max`/`step`.

## 2. Decisões de design (com o usuário)

| Decisão | Escolha |
|---|---|
| Criar própria vs usar integração pronta | **Criar integração própria** |
| Instalação | **HACS via repositório GitHub próprio** |
| Escopo de entidades | **Completo, como o Midea** (climate + sensores + switches/selects) |
| Comunicação | **SSE em tempo real desde o início, com polling de reconciliação** (cliente aiohttp próprio, sem dependência do SDK) |

## 3. Arquitetura

Domínio HA: `electrolux_ac`. Estrutura:

```
eletrolux-ac/
├── custom_components/electrolux_ac/
│   ├── __init__.py          # setup do entry: cria client, coordinator, inicia SSE, forward platforms
│   ├── manifest.json        # domain, iot_class: cloud_push, config_flow: true, sem requirements
│   ├── const.py             # domínio, chaves, mapeamentos de modos HA<->API
│   ├── api.py               # ElectroluxApiClient (aiohttp)
│   ├── coordinator.py       # ElectroluxCoordinator (DataUpdateCoordinator)
│   ├── config_flow.py       # user step + reauth step
│   ├── entity.py            # ElectroluxEntity base (device_info, disponibilidade)
│   ├── climate.py           # entidade principal
│   ├── sensor.py            # temp ambiente, filtro, sinal WiFi
│   ├── switch.py            # capacidades readwrite com 2 valores tipo ON/OFF
│   ├── select.py            # capacidades readwrite com >2 valores
│   ├── binary_sensor.py     # conectividade
│   ├── strings.json + translations/en.json + translations/pt-BR.json
├── tests/                   # pytest-homeassistant-custom-component
├── hacs.json                # metadados HACS
├── openapi.json             # referência da API (extraída do portal)
├── .github/workflows/validate.yml  # hassfest + HACS validation
└── README.md                # instalação HACS, obtenção das chaves no portal
```

### 3.1 `api.py` — ElectroluxApiClient

- Sessão aiohttp compartilhada do HA (`async_get_clientsession`).
- Métodos: `async_get_appliances()`, `async_get_info(id)`, `async_get_state(id)`, `async_send_command(id, dict)`, `async_get_livestream_config()`, `async_refresh_token()`.
- Toda requisição: injeta os 2 headers; em `401`, faz refresh (com lock para evitar corrida), invoca callback `on_tokens_updated(access, refresh)` (o `__init__.py` persiste no config entry via `async_update_entry`) e repete a requisição **uma** vez. Refresh falhou → `ConfigEntryAuthFailed` → HA dispara reauth.
- SSE: `async_listen_events(callback)` — task de longa duração: obtém livestream config, conecta com `sock_read` sem limite e guarda de 120 s por linha, parseia `data:` JSON e chama o callback; em qualquer erro fecha a sessão, espera 10 s e reconecta (re-obtendo tokens). Uma única conexão SSE por config entry (limite da API).

### 3.2 `coordinator.py` — ElectroluxCoordinator

- No `async_config_entry_first_refresh`: lista aparelhos → filtra tipo AC (`applianceType == "AC"` ou `deviceType` contendo `AIR_CONDITIONER`) → busca `info` (capabilities, uma vez; guardadas no coordinator) e `state` de cada um.
- Dados: `dict[applianceId] -> {info, capabilities, state}`.
- **Push:** o callback SSE aplica `{property, value}` no estado em memória (mesma lógica `apply_sse_update` do SDK: caminho com `/` dentro de `properties.reported`; `connectionState`/`connectivityState` no topo) e chama `async_set_updated_data` — entidades atualizam instantaneamente.
- **Reconciliação:** `update_interval = 5 min` re-busca o `state` de cada AC (~288 chamadas/dia por aparelho; quota de 5000/dia comporta com folga).
- Após `async_send_command`: atualização otimista no estado em memória + push; o SSE/poll confirma o valor real.

### 3.3 `config_flow.py`

- Passo `user`: campos `api_key`, `access_token`, `refresh_token` (texto, com descrição de onde obter no portal). Validação: chamada real a `GET /appliances`; erros mapeados (`invalid_auth`, `cannot_connect`).
- `unique_id` do entry: hash da API key (evita duplicar a mesma conta).
- Passo `reauth`: reapresenta os 3 campos quando `ConfigEntryAuthFailed`.
- Tokens atualizados em runtime são gravados de volta no entry (`entry.data`), sobrevivendo a restart.

### 3.4 Entidades (capability-driven)

Regra geral: uma entidade só é criada se a capability correspondente existir no `/info` do aparelho; opções/limites vêm da capability, nunca hardcoded.

- **`climate.py`** (1 por AC):
  - `hvac_modes`: mapeia `mode.values` → `COOL→cool`, `AUTO→auto`, `DRY→dry`, `FANONLY→fan_only`, `HEAT→heat` (se existir) + `off` sempre.
  - Ligar/desligar: comando `{"executeCommand": "ON"/"OFF"}`; estado ligado = `applianceState == RUNNING` (senão `mode != OFF`).
  - `target_temperature`: `targetTemperatureC` com `min/max/step` da capability; usa `targetTemperatureF` quando `temperatureRepresentation == FAHRENHEIT`.
  - `fan_modes`: valores de `fanSpeedSetting` (AUTO/LOW/MIDDLE/HIGH → auto/low/medium/high).
  - `swing_modes`: de `verticalSwing` (ON/OFF); se o modelo tiver `horizontalSwing`, incluir via `swing_horizontal_mode` (HA ≥ 2024.12) ou select dedicado.
  - `current_temperature`: `ambientTemperatureC/F`.
- **`sensor.py`**: `ambientTemperatureC` (°C, device_class temperature), `filterState` (enum), `networkInterface.linkQualityIndicator` (enum, categoria diagnóstico).
- **`switch.py`**: capacidades `readwrite` booleanas/binárias: `sleepMode`, `cleanAirMode`, `uiLockMode`, `schedulerMode`, e `displayLight` quando tiver exatamente 2 valores (mapeia DISPLAY_LIGHT_0=off / DISPLAY_LIGHT_1=on). Categoria `config` (aparecem na seção Configuração, como no Midea).
- **`select.py`**: capacidades `readwrite` de string com >2 valores que não são cobertas pelo climate.
- **`binary_sensor.py`**: `connectionState` (device_class connectivity, categoria diagnóstico).
- **Disponibilidade:** entidades ficam `unavailable` quando `connectionState != "connected"` ou após falhas repetidas do coordinator.
- **Device registry:** um device por AC com `identifiers={(DOMAIN, applianceId)}`, nome do alias do app, `manufacturer` = brand do info, `model` = model/variant, `sw_version` = `networkInterface.swVersion`.

## 4. Tratamento de erros

- `401` → refresh + retry (uma vez) → se falhar, reauth flow com notificação nativa do HA.
- `429`/erros de rede no poll → `UpdateFailed` (o DataUpdateCoordinator já aplica backoff exponencial nativo); entidades só ficam indisponíveis após falhas consecutivas.
- SSE cai → reconexão com espera de 10 s; o poll de 5 min mantém consistência nesse meio-tempo.
- `406` ao enviar comando (ex. AC desligado da tomada) → `HomeAssistantError` com mensagem amigável (aparece como toast na UI).
- Aparelho removido da conta → entidades ficam indisponíveis; log de aviso.

## 5. Testes

- `pytest` + `pytest-homeassistant-custom-component`; fixtures JSON derivadas dos exemplos reais do `openapi.json`.
- Cobertura mínima: config flow (sucesso/auth inválida/reauth), refresh de token com rotação e persistência, `apply_sse_update` (propriedade simples, caminho aninhado, connectionState), mapeamento climate (modos, limites de temperatura, fan), geração dinâmica de entidades a partir de capabilities, comando com atualização otimista.
- CI (GitHub Actions): `hassfest` + `HACS validation` + pytest.

## 6. Segurança

- `.env` e `*.har` no `.gitignore` — o `.har` contém tokens de sessão do portal e **não pode** ir ao GitHub. As credenciais reais vivem apenas no config entry do HA (armazenamento padrão do HA).

## 7. Fora de escopo (v1)

- Interpretação de `triggers` das capabilities (regras condicionais entre propriedades).
- Suporte a outros tipos de aparelho Electrolux (só AC).
- Agendamentos (`schedulerMode` é exposto como switch, sem UI de horários).
- Publicação no HACS default store (fica como custom repository).
