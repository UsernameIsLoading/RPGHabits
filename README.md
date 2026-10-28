# RPG de Hábitos — versão multiplayer/offline (base inicial)

Aplicação web em Flask + SQLAlchemy, preparada para PostgreSQL no servidor e SQLite local. A interface tem tema pixel art, sprites de classe, seleção de classe no primeiro acesso, tarefas configuráveis, relíquias vinculadas à conta, PWA instalável e base de sincronização offline.

> **Limitação importante desta versão:** a base de contas, sincronização e interface offline foi adicionada, mas a dungeon e o combate continuam sendo processados pelo servidor. Iniciar dungeon, movimentar-se e realizar ações de combate exigem conexão nesta versão. Não é simulado um combate local com regras diferentes do motor Python.

## O que inclui

- **Múltiplas contas:** registro com senha protegida por hash, login e dados isolados por conta. Esta base ainda não inclui PvP ou cooperação em tempo real; essas modalidades precisam de regras e implementação próprias.
- **Administração:** a conta `ADMIN_USERNAME` (por padrão, `admin`) acessa `/admin`; pode baixar um backup lógico JSON, enviar/restaurar um backup no mesmo formato e baixar as dez cópias automáticas anteriores a restaurações. A restauração substitui os dados de todos os jogadores, pede confirmação e limita uploads a 50 MB.
- **Classes:** Guardião (HP), Sentinela (DEF), Lutador (ATK), Duelista (AGI), Invocador (MP), Arcanista (MAG), Monge (RES) e Explorador (LUC). A seleção ocorre uma única vez no primeiro acesso. O atributo dominante recebe o dobro da XP de avaliação: 0/6/12/18 para avaliações 0/3/6/9, respetivamente; as demais avaliações continuam em 0/3/6/9.
- **Tarefas configuráveis:** cada atributo pode ter uma tarefa própria; os nomes precisam ser únicos para evitar que a mesma tarefa conte para mais de um atributo.
- **Relíquias Vinculadas:** apenas Manto do Herói Esquecido, Anel do Investidor Nato e Pingente da Deusa do Amor. As duas relíquias de efeito contínuo são permanentes e só uma pode ficar ativa por vez; o Pingente é consumível. Os preços iniciais (2500/1500/500 moedas) são valores provisórios de balanceamento.
- **PWA:** manifesto, service worker no escopo raiz (controla o site inteiro), cache de recursos e armazenamento local em IndexedDB, com fallback para localStorage nos navegadores sem IndexedDB.
- **Fila de sincronização:** ações compatíveis com modo offline são guardadas localmente com identificadores idempotentes e enviadas quando a conexão volta. A configuração de tarefas usa versão para detectar mudanças concorrentes; a interface pode pedir para manter ou descartar uma alteração conflitante.
- **Preservação das regras existentes:** atributos, ranks, habilidades, equipamentos, monstros, loja original, dungeon e combate por turnos continuam no motor existente.

## O que funciona offline nesta versão

Depois de abrir o jogo conectado ao menos uma vez, o aplicativo pode carregar a interface em cache e recuperar o estado local da conta no mesmo navegador/dispositivo. Avaliações de hábitos, registros de atividade, alteração das tarefas, compras compatíveis, uso de poções fora do combate, equipar/retirar equipamentos e algumas operações de relíquias podem ser registradas localmente e sincronizadas posteriormente.

- A dungeon e as ações de combate ainda exigem conexão.
- Os sites externos de recompensa (YouTube, Wikipedia, WEBTOON, ChatGPT e a página da novel) exigem internet. O jogo não inicia uma nova sessão de recompensa quando está offline.
- Login, cadastro, primeira escolha de classe, exportação/restauração e sincronização exigem conexão.
- A conta offline só tem os dados que já foram guardados nesse navegador. Limpar os dados do navegador ou perder o aparelho antes da sincronização pode apagar mudanças que ainda não chegaram ao servidor. Evite jogar offline em dispositivos compartilhados.
- A sincronização é por conta e as alterações recebem identificadores idempotentes. Conflitos de tarefas e relíquias permitem escolher uma versão; uma avaliação duplicada exige preservar a que já foi confirmada no servidor ou adiar a decisão. O banner de conflito pode ser tocado para reabrir a tela.

## Executar localmente

Requer Python 3.11+.

### Windows (PowerShell)

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
$env:ADMIN_USERNAME="admin"
$env:ADMIN_PASSWORD="escolha-uma-senha-forte"
$env:SECRET_KEY="troque-por-uma-chave-longa-e-aleatoria"
python app.py
```

### Linux/macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
export ADMIN_USERNAME=admin
export ADMIN_PASSWORD='escolha-uma-senha-forte'
export SECRET_KEY='troque-por-uma-chave-longa-e-aleatoria'
python app.py
```

Abra `http://127.0.0.1:5000`. Sem `DATABASE_URL`, o sistema usa `instance/rpg_habitos.db` (SQLite). A conta administrativa inicial é o valor de `ADMIN_USERNAME`, com a senha fornecida em `ADMIN_PASSWORD`. Para instalações anteriores, `SITE_PASSWORD` é usado como fallback durante a criação inicial da conta administrativa. A senha existente não é redefinida automaticamente em cada inicialização.

## Publicar no Render

1. Envie os arquivos para um repositório Git e crie um Blueprint no Render usando `render.yaml`.
2. Defina `ADMIN_PASSWORD` como uma senha forte no Render. `ADMIN_USERNAME` começa como `admin`; `SECRET_KEY` é gerada pelo Blueprint e `DATABASE_URL` aponta para PostgreSQL.
3. Depois do deploy, abra o serviço, entre na conta administrativa e conclua a escolha de classe, se for solicitada.
4. Para abrir a administração, use o ícone de engrenagem no jogo ou visite `/admin` após entrar como admin.

Comandos para Web Service manual:

- Build Command: `pip install -r requirements.txt`
- Start Command: `gunicorn app:app`
- Health Check Path: `/`
- Variáveis: `SECRET_KEY`, `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `DATABASE_URL`

**Migração de versões antigas:** a inicialização adiciona colunas ao banco e tenta associar o personagem único anterior à conta administrativa. Faça download de um backup antes de atualizar uma instalação que já tenha progresso.

## Backups administrativos

O botão **Baixar backup completo** exporta um backup lógico JSON desta versão, contendo contas (inclusive hashes de senha), personagens, avaliações, atividades, tentativas de dungeon e chaves idempotentes da sincronização. O arquivo permite restaurar os dados dentro desta aplicação; não é um dump SQL nativo do PostgreSQL. Guarde o arquivo em local privado. Antes de qualquer restauração, o sistema guarda uma cópia compactada do banco atual; as dez cópias automáticas mais recentes podem ser baixadas pela área administrativa. Restaurar substitui os dados de domínio e encerra a sessão para exigir novo login.

## Testes e verificações

```bash
python -m unittest discover -s tests -v
python -m py_compile app.py game_data.py game_engine.py
node --check static/app.js
```

A suíte independente do motor pode ser executada sem Flask. Testes de integração web precisam ser executados em um ambiente com as dependências de `requirements.txt` instaladas.

## Estrutura

```text
app.py                  rotas, autenticação, persistência, migração e APIs
app_pre_multiplayer.py  cópia de referência da versão anterior
 game_data.py            catálogo de habilidades, equipamentos, monstros e itens
 game_engine.py          progressão, dungeon, combate, efeitos e loot
templates/login.html     entrada/criação de conta
templates/setup.html     escolha de classe única no primeiro acesso
templates/index.html     interface de jogo
 templates/admin.html    backups administrativos
static/app.js            interface, cache local e fila de sincronização
static/service-worker.js cache da PWA e política de atualização adiada
static/sprites/          sprites pixel-art das classes
tests/test_engine.py     testes do motor
a render.yaml            configuração do deploy no Render
```


### Migração única do progresso antigo

Na primeira inicialização desta versão, se existir uma conta `shiksz`, o aplicativo transfere para ela o perfil legado que estava associado à conta administrativa padrão. A operação mantém os registros, combina inventário/moedas e avaliações sem apagar o restante do banco, dobra o XP histórico de RES uma única vez e grava um marcador no usuário para não repetir a transferência. O destino pode ser alterado com a variável `LEGACY_PROGRESS_TARGET_USERNAME`; não configure essa variável para uma conta que não deva receber o progresso. Faça backup do banco antes de implantar.
