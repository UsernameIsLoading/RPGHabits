# RPGHabits — atualização de progressão, Biblioteca e scoreboard

Aplicação web em Flask + SQLAlchemy, preparada para PostgreSQL no servidor e SQLite local. A interface mantém o tema pixel art, sprites de classe, criação de personagem única, relíquias vinculadas à conta e PWA instalável com sincronização offline.

> **Limitação importante desta versão:** a base de contas, sincronização e interface offline foi adicionada, mas a dungeon e o combate continuam sendo processados pelo servidor. Iniciar dungeon, movimentar-se e realizar ações de combate exigem conexão nesta versão. Não é simulado um combate local com regras diferentes do motor Python.

## O que inclui nesta atualização

- **Contas e dados isolados:** registro, login e persistência por jogador.
- **Criação de personagem:** classe, oito tarefas e site de recompensa são escolhidos no primeiro acesso. Depois de confirmar, classe, tarefas e site ficam bloqueados; a rota antiga de edição de tarefas recusa alterações.
- **Progressão acelerada:** F=0, E=9, D=36, C=117, B=360, A=1089 e S=3276 XP acumulados. As autoavaliações continuam em 0/3/6/9 XP, com XP em dobro no atributo dominante da classe.
- **Habilidades iniciais de classe:** Guardião — Fortaleza Interior (cura + DEF); Sentinela — Postura Inabalável (DEF temporária); Lutador — Golpe Devastador (bônus no próximo ataque); Duelista — Passo Fantasma (AGI + esquiva); Invocador — Espírito Guardião (reduz o próximo dano); Arcanista — Descarga Arcana (ataque mágico); Monge — Equilíbrio Vital (RES temporária); Explorador — Instinto Predador (bônus no próximo ataque + esquiva). Cada habilidade sobe automaticamente de estágio quando o atributo dominante muda de rank.
- **Recompensa individual:** o jogador define um nome e URL durante a criação. Não há lista fixa de sites nem opção de troca em outra página. O saldo diário e o saldo especial da dungeon mantêm suas regras.
- **Biblioteca:** cada conta pode enviar livros, provas, apostilas e outros documentos (PDF, EPUB, texto, documentos, planilhas e apresentações). Cada minuto com a aba visível concede 1 moeda, até 60 minutos/60 moedas por dia, compartilhados entre todos os arquivos. O acesso aos arquivos não tem limite de uso. Arquivos enviados ficam privados para a conta proprietária.
- **Scoreboard:** lista nome de usuário, rank médio dos oito atributos e classe. Não exibe XP individual, moedas, inventário ou hábitos.
- **Dungeon cooperativa:** convites entre jogadores, mapa e inimigos compartilhados, turnos alternados, HP/MP e loot individuais, consumo de 2 Tickets por participante, regras de morte/vitória e abandono por consentimento dos dois. A Pena da Fênix (100 moedas) ressuscita o parceiro fora de combate com 10 HP e 10 MP.
- **Administração e backups:** a conta administrativa continua podendo baixar/restaurar backups lógicos. O backup agora inclui os documentos da Biblioteca.
- **PWA:** manifesto, service worker, cache de recursos e armazenamento local em IndexedDB, com fallback para localStorage nos navegadores sem IndexedDB.

> **Multiplayer:** o scoreboard e a dungeon cooperativa de dois jogadores estão implementados. A cooperação usa conexão com o servidor durante exploração e combate; não é processada offline. Veja `MULTIPLAYER_COOP_SPEC.md` para as regras completas.

## O que funciona offline nesta versão

Depois de abrir o jogo conectado ao menos uma vez, o aplicativo pode carregar a interface em cache e recuperar o estado local da conta no mesmo navegador/dispositivo. Avaliações de hábitos, registros de atividade, compras compatíveis, uso de poções fora do combate, equipar/retirar equipamentos e algumas operações de relíquias podem ser registradas localmente e sincronizadas posteriormente.

- A dungeon individual e a cooperativa, incluindo movimentação e ações de combate, exigem conexão.
- O scoreboard e o site externo de recompensa exigem internet. A Biblioteca exige conexão para enviar, baixar e contar moedas de forma validada pelo servidor.
- Login, cadastro, configuração inicial do personagem, exportação/restauração e sincronização exigem conexão.
- A conta offline só tem os dados já guardados nesse navegador. Limpar os dados do navegador ou perder o aparelho antes da sincronização pode apagar mudanças que ainda não chegaram ao servidor.
- A sincronização é por conta e as alterações recebem identificadores idempotentes. Conflitos de avaliação diária continuam exigindo cuidado para evitar XP duplicado.

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
app.py                  rotas, autenticação, persistência, migração, APIs e expedições cooperativas
app_pre_multiplayer.py  cópia de referência da versão anterior
game_data.py             catálogo de habilidades, equipamentos, monstros e itens
game_engine.py           progressão, dungeon, combate, efeitos e loot
templates/login.html     entrada/criação de conta
templates/setup.html     configuração única de classe, tarefas e recompensa
templates/index.html     interface de jogo
templates/admin.html     backups administrativos
static/app.js            interface, cache local e fila de sincronização
static/service-worker.js cache da PWA e política de atualização adiada
static/sprites/          sprites pixel-art das classes
tests/test_engine.py     testes do motor
render.yaml              configuração do deploy no Render
```


### Migração única do progresso antigo

Na primeira inicialização desta versão, se existir uma conta `shiksz`, o aplicativo transfere para ela o perfil legado que estava associado à conta administrativa padrão. A operação mantém os registros, combina inventário/moedas e avaliações sem apagar o restante do banco, dobra o XP histórico de RES uma única vez e grava um marcador no usuário para não repetir a transferência. O destino pode ser alterado com a variável `LEGACY_PROGRESS_TARGET_USERNAME`; não configure essa variável para uma conta que não deva receber o progresso. Faça backup do banco antes de implantar.
