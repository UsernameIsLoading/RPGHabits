# RPGHabits — dungeon cooperativa

A dungeon cooperativa de dois jogadores está implementada nesta versão. O scoreboard continua disponível na aba Multiplayer.

## Como iniciar

1. Os dois jogadores precisam ter concluído a criação de personagem e estar fora de uma dungeon individual.
2. Um jogador envia um convite pelo nome de usuário; o outro aceita ou recusa.
3. Ao aceitar, o servidor confere os inventários e consome **2 Tickets de Dungeon de cada jogador** (4 no total).
4. A expedição compartilhada começa após a aceitação. Convites pendentes expiram após 24 horas.

## Como funciona a expedição

- A dupla compartilha um mapa, posição, andares, baús, inimigos e avanço.
- Cada participante mantém seu próprio HP, MP, equipamentos, habilidades, recargas, poções de dungeon, moedas e loot.
- Os jogadores alternam ações de exploração. Em combate, a iniciativa começa pelo jogador com maior AGI (empate aleatório); depois os turnos alternam entre os participantes vivos. O inimigo responde segundo as regras normais do motor de combate.
- Poções encontradas em baús são atribuídas ao jogador que abriu o baú. Moedas de baús e recompensas de monstros são creditadas individualmente a quem as encontrou ou derrotou o monstro.
- O combate e as ações cooperativas exigem conexão com o servidor. O estado é salvo para que os dois possam atualizar a tela e continuar de dispositivos diferentes.

## Morte, vitória e ressurreição

- Se os dois personagens forem derrotados, ambos perdem o loot temporário da expedição. As moedas já conquistadas são preservadas e ambos retornam com 10 HP e 10 MP.
- Se um personagem for derrotado e o parceiro concluir a dungeon, ambos preservam seus próprios equipamentos temporários conquistados. Somente quem terminar vivo recebe os 40 minutos especiais.
- Se os dois concluírem vivos, ambos preservam o próprio loot e recebem 40 minutos especiais.
- A **Pena da Fênix** custa 100 moedas, fica no Espaço de Utilidade e só pode ser usada por um participante vivo para ressuscitar o parceiro derrotado. Ela só pode ser usada fora de combate; o aliado retorna com 10 HP e 10 MP, e a pena é consumida.
- Para evitar que um jogador encerre a expedição contra a vontade do parceiro, o abandono exige solicitação de um jogador e confirmação do outro. O abandono acordado encerra a dungeon e descarta o loot temporário, preservando moedas.

## Persistência e segurança

- A expedição é armazenada em uma tabela própria (`coop_expedition`); o progresso de cada jogador permanece na conta individual.
- As rotas de mutação bloqueiam a expedição e os dois registros de personagem durante as ações, para reduzir atualizações concorrentes.
- Equipar itens, usar poções fora do combate e iniciar uma dungeon solo ficam bloqueados enquanto houver convite pendente ou expedição ativa.
- O backup administrativo inclui as expedições cooperativas.
- A tabela nova é criada pela inicialização normal do banco (`db.create_all()` em `migrate_schema`); não é necessário apagar nem recriar o banco.
