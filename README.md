# RPG de Hábitos — Build 01.0

Aplicação web de um jogador, construída do zero com Flask, SQLAlchemy e PostgreSQL/SQLite. Não depende de nenhum projeto chamado A Travessia.

## O que já está no projeto

- Quatro áreas: **Atributos**, **Dungeon**, **Painel** e **Recompensas**.
- Oito atributos associados a hábitos diários, progressão independente F→S e autoavaliação de 0/3/6/9 XP, uma vez por atributo por dia.
- Registro de atividades com texto, número e observação, além de edição/exclusão e gráficos com filtro de período e agregação por dia/semana/mês.
- Catálogo de 56 habilidades, 24 equipamentos e 12 monstros, com fontes de loot únicas por monstro.
- Dungeon de 3 a 7 andares; mapa 6×6; visão local; movimentação em oito direções; baús; combate por turnos; loot temporário; moedas preservadas após derrota; no máximo duas entradas por janela móvel de sete dias.
- Duas poções consumíveis: **Poção de Cura** (+8 HP) e **Poção de Mana** (+6 MP). A personagem começa com duas de cada. Poções nunca ultrapassam o máximo de HP/MP; durante o combate, usá-las gasta a ação do turno.
- Recompensas de tempo de lazer e desbloqueio de capítulos ímpares por treino físico e pares por estudos. O site da novel é aberto na fonte oficial; o projeto não copia nem armazena o texto da obra.
- Código de acesso único, em vez de sistema de contas múltiplas.

## Executar localmente

Requer Python 3.11 ou mais recente.

### Windows (PowerShell)

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
$env:SITE_PASSWORD="12345678"
$env:SECRET_KEY="troque-por-uma-chave-longa-e-aleatoria"
python app.py
```

### Linux/macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
export SITE_PASSWORD="12345678"
export SECRET_KEY="troque-por-uma-chave-longa-e-aleatoria"
python app.py
```

Abra `http://127.0.0.1:5000`. Sem `DATABASE_URL`, o app cria `instance/rpg_habitos.db` automaticamente. Não exclua esse arquivo se quiser preservar os dados locais.

O código local padrão é `12345678`. Mude-o para seu próprio código antes de usar em uma rede compartilhada.

## Publicar no Render

O repositório inclui `render.yaml` (Blueprint), `requirements.txt` e `Procfile`.

1. Envie o conteúdo desta pasta para um repositório Git.
2. No Render, crie um **Blueprint** a partir do repositório e aplique o `render.yaml`.
3. Quando solicitado, defina `SITE_PASSWORD` como um código de oito dígitos que só você conheça. `SECRET_KEY` é gerada pelo Blueprint e `DATABASE_URL` é ligado ao PostgreSQL criado pelo Blueprint.
4. Depois do deploy, abra a URL do serviço e entre com o código configurado.

Comandos equivalentes para um Web Service manual:

- **Build Command:** `pip install -r requirements.txt`
- **Start Command:** `gunicorn app:app`
- **Health Check Path:** `/`
- **Variáveis:** `SECRET_KEY`, `SITE_PASSWORD`, `DATABASE_URL`

### Atenção à persistência no plano gratuito

O serviço web gratuito do Render não mantém dados gravados no sistema de arquivos local entre reinicializações. Por isso o Blueprint usa PostgreSQL, e não o SQLite local. **O PostgreSQL gratuito do Render expira 30 dias após sua criação**; para manter o progresso a longo prazo, faça upgrade do banco antes da expiração ou configure `DATABASE_URL` para um PostgreSQL com persistência contínua. Consulte a documentação atual do Render antes de publicar: <https://render.com/docs/free>.

## Regras de balanceamento adotadas provisoriamente

As regras confirmadas pelo jogador estão incorporadas no motor. Para que a primeira versão rode sem mais bloqueios, alguns números sem definição explícita no documento foram configurados como padrões iniciais e podem ser alterados nos arquivos `game_engine.py`:

- Poção de Cura: +8 HP; Poção de Mana: +6 MP; inventário inicial: duas de cada.
- Baús: 62% de chance de conter poção, com uma ou duas unidades; moedas independentes.
- Cada item listado no loot tem chance independente de 45% de cair.
- Faixas-base de moedas: comum 4–10, forte 12–24, chefe 30–50; o rank do monstro ajusta a faixa por multiplicador.
- Esquiva: 5% inicial, +5 pontos percentuais por ponto de vantagem de AGI defensiva, limitada a 60%; Pós-imagem soma 20 pontos percentuais, respeitando teto de 80%.
- O crédito fracionário de Fórmula Eficiente acumula durante uma dungeon e é descartado quando ela termina ou o jogador morre.
- Enquanto a lista de itens é fechada e não há variantes de raridade, o efeito de melhoria de raridade de LUC gera uma pequena recompensa em moedas; a mensagem do jogo indica esse comportamento provisório.
- Dois equipamentos ainda não têm fonte de drop na lista atual: **Braçadeira do Guardião** e **Luvas do Lutador**. Continuam no catálogo e podem receber uma fonte em balanceamento futuro, sem duplicar os drops já definidos.

Esses padrões não são apresentados como regras originais do documento; estão destacados para facilitar a revisão do balanceamento.

## Testes

O motor independente do framework é testado com:

```bash
python -m unittest discover -s tests -v
python -m py_compile app.py game_data.py game_engine.py
node --check static/app.js
```

## Estrutura

```text
app.py                 Rotas web, autenticação, persistência e APIs
game_data.py           Catálogo de habilidades, equipamentos, monstros e poções
 game_engine.py        Progressão, dungeon, combate, efeitos, loot e moedas
 templates/login.html Acesso por código
 templates/index.html Interface principal e janelas de recompensa
 static/app.js         Interface dinâmica e chamadas de API
 static/style.css      Tema visual responsivo
 tests/test_engine.py  Testes básicos do motor
 render.yaml           Blueprint do Render
 requirements.txt      Dependências Python
```
