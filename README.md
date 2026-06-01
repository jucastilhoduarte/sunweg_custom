# SunWEG Custom Integration for Home Assistant

Este repositório contém uma integração **não oficial** para o [Home Assistant](https://www.home-assistant.io) que permite monitorar usinas solares cadastradas na plataforma **SunWEG**. A integração autentica com sua conta do SunWEG, obtém um token de acesso e expõe uma série de sensores para acompanhar a produção de energia, potência instantânea, leituras do inversor, impactos ambientais e economia financeira.

> **Aviso:** Esta integração é um _custom component_ e não substitui nenhum componente do Home Assistant Core. Ela não é afiliada à WEG nem ao time oficial do Home Assistant. Use por sua conta e risco.

## Recursos

- **Fluxo de configuração via UI**: configure a integração diretamente na interface do Home Assistant, informando usuário/senha ou um token de sessão do SunWEG. A lista de usinas disponíveis é carregada automaticamente no formato `id - nome` para facilitar a seleção.
- **Reaproveitamento de token**: a integração armazena o token de acesso e reutiliza a sessão em reinicializações do Home Assistant. Quando usuário/senha também foram configurados, ela tenta obter um novo token automaticamente se a sessão expirar.
- **Dispositivo único por usina**: todos os sensores são agrupados em um único dispositivo correspondente à usina monitorada.
- **Sensores por usina** — lidos diretamente do endpoint `viewresumov2`:

  | Grupo       | Sensor                  | Unidade                         |
  | ----------- | ----------------------- | ------------------------------- |
  | Energia     | Energia gerada hoje     | kWh                             |
  | Energia     | Energia gerada no mês   | kWh                             |
  | Energia     | Energia gerada no ano   | kWh                             |
  | Energia     | Energia gerada total    | kWh                             |
  | Potência    | Potência atual          | kW                              |
  | Instalação  | Capacidade instalada    | kWp                             |
  | Status      | Status da usina         | —                               |
  | Status      | Problemas detectados    | contagem + atributo `mensagens` |
  | Ambiental   | CO₂ evitado             | t                               |
  | Ambiental   | Árvores plantadas       | —                               |
  | Ambiental   | Quilômetros elétricos   | km                              |
  | Financeiro  | Economia hoje           | BRL                             |
  | Financeiro  | Economia total          | BRL                             |
  | Performance | Yield diário            | kWh/kWp                         |
  | Performance | Yield mensal            | kWh/kWp                         |
  | Inversor    | Temperatura do inversor | °C                              |
  | Inversor    | Frequência AC           | Hz                              |
  | Inversor    | Tensão AC               | V                               |
  | Inversor    | Corrente AC             | A                               |
  | Timestamp   | Última leitura          | —                               |

- **Sensor de problemas inteligente**: o estado é a contagem de problemas ativos (útil para automações com `> 0`). O atributo `mensagens` contém a lista detalhada de ocorrências com as tags HTML removidas, podendo ser exibida em um Markdown card:

  ```yaml
  type: markdown
  visibility:
    - condition: numeric_state
      entity: sensor.usina_solar_problemas_detectados
      above: 0
  content: >-
    ## ⚠️ Problemas detectados

    {% for m in state_attr('sensor.usina_solar_problemas_detectados', 'mensagens') %}
    - {{ m }}
    {% endfor %}
  ```

- **`last_updated` honesto**: o HA só avança o timestamp de atualização de cada sensor quando o inversor produz uma leitura nova (campo `ultimaleitura` da API). Polls que retornam os mesmos dados não atualizam o histórico.

## Instalação

### Via HACS (recomendado)

1. Adicione este repositório no HACS como um repositório personalizado de tipo _Integration_.
2. Instale a integração **SunWEG** pelo HACS.
3. Reinicie o Home Assistant.
4. Acesse **Configurações → Dispositivos e Serviços → Adicionar Integração**, busque por **SunWEG** e siga o assistente para informar usuário/senha ou token de sessão e escolher a usina.

> **Observação sobre o ícone:** os arquivos `logo.png` e `icon.png` presentes na raiz deste repositório são usados pelo HACS para exibir um logotipo personalizado. Eles não precisam ser copiados para o Home Assistant; basta mantê‑los no seu GitHub.

### Instalação manual

1. Faça o download deste repositório e copie a pasta `custom_components/sunweg_custom` para o diretório `config/custom_components` da sua instalação do Home Assistant.
2. Reinicie o Home Assistant.
3. Siga os passos do fluxo de configuração via UI (Configurações → Dispositivos e Serviços → Adicionar Integração → SunWEG).

## Como funciona

- **Autenticação:** a integração pode usar os endpoints de login da API SunWEG para autenticar com seu e-mail e senha, ou reutilizar um token obtido após login manual no portal. Nas chamadas de dados, o valor é enviado no header `X-Auth-Token-Update`.
- **Login manual:** se o portal exigir verificação humana no login, faça o login normalmente no navegador com **permanecer conectado** marcado e copie o valor do header `X-Auth-Token-Update` de uma chamada para `https://api.sunweg.net/v2/...` nas ferramentas de desenvolvedor. Cole esse valor no campo **Token de sessão** do fluxo de configuração; a integração também aceita o header completo colado nesse campo.
- **Fonte de dados:** todas as métricas são obtidas de uma única chamada ao endpoint `viewresumov2`, que retorna o estado completo da usina — leituras do inversor, totais históricos, status, problemas e timestamp da última coleta.
- **Coordenador de dados:** um [DataUpdateCoordinator](https://developers.home-assistant.io/docs/data_update_coordinator_index/) gerencia as chamadas periódicas à API (intervalo padrão de 5 minutos), tratando erros de conexão e renovação do token.

## Contribuindo

Sinta‑se à vontade para abrir issues ou enviar _pull requests_ para melhorias. Como esta é uma integração de terceiros, testes adicionais são sempre bem‑vindos.
