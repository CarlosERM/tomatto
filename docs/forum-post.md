# Testes de integração com GenAI: o que funcionou, o que me enganou (Tomatto)

Repositório: https://github.com/CarlosERM/tomatto

## O que eu construí

O **Tomatto** é um bloqueador de sites simples, sem interface. Ele tem três partes conversando por HTTP:

1. **Manager API** (`:3001`) — guarda a lista de domínios bloqueados num SQLite. Toda mudança gera um número de versão que só cresce.
2. **Sync API** (`:3002`) — recebe a lista inteira da Manager e entrega para quem consultar. Usa cache: se nada mudou, responde `304 Not Modified` em vez de mandar a lista de novo.
3. **Extensão Chrome (Manifest V3)** — busca a lista a cada minuto e bloqueia os sites.

O objetivo do exercício era usar uma GenAI para gerar os **casos de teste de integração** — aqueles testes que verificam se as peças conversam direito entre si, não se cada função isolada funciona.

Escrevi quatro prompts com intenções diferentes:

| Prompt | O que eu pedi |
|---|---|
| **P1 — Contrato** | "Aqui está a especificação OpenAPI; gere os testes de contrato" |
| **P2 — Cenários** | "Descreva cenários ponta a ponta no formato Given/When/Then" |
| **P3 — Casos de erro** | "Aja como QA adversarial e quebre a integração entre os serviços" |
| **P4 — Dados de teste** | "Gere dados de teste realistas e maliciosos para essa API" |

Cada prompt tem uma versão 1 (ingênua) e uma versão 2 (revisada). Rodei as duas, **oito execuções no total**, com um modelo local (Qwen3.8 Flash Next no LM Studio), cada uma em uma conversa zerada, sem acesso ao código do projeto. As respostas brutas estão todas em [`generated-tests/`](../generated-tests/) — sem edição nenhuma.

## A surpresa: o problema não foi "IA escreve teste fraco"

Eu esperava achar que a IA gera teste raso, tipo "testa se retorna 200". Não foi isso que aconteceu. Em três dos quatro prompts, a versão 1 veio **cheia de detalhes, bem formatada e tecnicamente correta**. O P1, por exemplo, devolveu código pytest pronto para rodar, validando o JSON contra o schema da especificação, cobrindo os sete endpoints — sem inventar um endpoint sequer.

O problema foi outro: **falta de ancoragem**. A IA usou a qualidade dela em coisas que não existem no meu sistema. No P2 ela pediu teste de autenticação com token e rotação de credencial, de bloqueio com hora para expirar, de sincronização por delta, de paginação — nada disso existe no Tomatto. E, no meio de trinta cenários, ela nunca citou os três mecanismos que realmente seguram a integração: o push síncrono a cada mudança, a versão monotônica e o campo `sync_status="pending"`.

Resumo honesto do que mudou da v1 para a v2:

| Prompt | Versão 1 (ingênua) | Versão 2 (revisada) |
|---|---|---|
| **P1** | pytest executável, mas mudo sobre rejeição de versão antiga; e usava `pytest.skip` quando a Sync estava fora do ar — ou seja, uma integração quebrada ficaria **verde** | 19 linhas de checklist, uma por promessa, incluindo as quatro regras entre os dois serviços |
| **P2** | ~30 cenários, mas inventou auth, expiração, delta sync e paginação | 7 cenários que sempre tocam as duas APIs e dizem qual costura estão testando; nenhuma invenção |
| **P3** | ~50 casos genéricos de segurança (JWT, gzip bomb, IDOR) — nenhum alcançável num demo local de dois serviços | 14 casos entre os dois serviços, com o sintoma que o usuário veria se desse errado |
| **P4** | Aqui sim a previsão acertou: 20 nomes de marca (`facebook.com`, `youtube.com`…) e zero caso limite | 12 aceitos + 8 rejeitados exatos, com punycode correto (conferi contra a biblioteca `idna` do Python) |

Ou seja: o que fez diferença não foi pedir "testes melhores", foi **descrever o mecanismo e proibir saída fora dele**. Ancorar funcionou; elogiar e dar liberdade, não.

## Dois achados que valeram mais que os próprios testes

**1. O erro estava no meu prompt, e a IA resolveu calada.** No P1 eu dei duas regras que se contradiziam: a regra 3 pedia um teste de rejeição de snapshot antigo (que retorna `409`), e a regra 4 proibia usar status code que não está na especificação. Só que a minha especificação **não documenta o `409`** — o FastAPI não consegue deduzir isso sozinho. A IA resolveu o impasse do jeito dela: desobedeceu a regra 4 e gerou o teste do `409`. O resultado é um teste afirmando uma promessa que a API cumpre mas nunca declarou. O defeito real, portanto, nem é de prompt: é **especificação incompleta**. Fica como próximo passo declarar o `409` no OpenAPI.

**2. Um cenário gerado previu um bug real.** No P2 v2 saiu um cenário dizendo que, durante uma queda da Sync, a extensão continua recebendo `304` contra uma versão velha e precisa continuar aplicando a lista antiga. Dias depois eu esbarrei exatamente nisso de verdade: a extensão tinha um ETag salvo, recebia `304`, e esse caminho saía antes da lógica que atualizava as regras — nada se atualizava e nenhum log aparecia. Um texto gerado por prompt apontou a armadilha antes do bug acontecer.

## O que nenhum prompt cobriu (e foi o que mais me custou)

Nenhum dos quatro tipos de prompt falou sobre o **consumidor final**, a extensão. E foi lá que o projeto quebrou por dias.

A extensão registrava as regras de bloqueio sem erro nenhum, a contagem de regras batia, o dump das regras mostrava tudo certo — e nada era bloqueado. Sem log, sem exceção, site abria normalmente. A causa: a permissão `declarativeNetRequest` dá acesso automático apenas às regras do tipo `allow`, `allowAllRequests` e `block`. Regra de **redirecionamento** (que é o que eu usava para mostrar a página 🍅) exige `host_permissions` para os sites afetados. Sem isso, o Chrome aceita a regra mas nunca a aplica.

Detalhe que quase estragou a correção: ao adicionar o campo novo no `manifest.json`, ficou **duas vezes** a chave `host_permissions`. JSON mantém só a última — então meu conserto seria ignorado em silêncio e eu continuaria achando que o problema era outro.

A lição que ficou: a GenAI testou muito bem cada costura que eu descrevi, e ignorou por completo as que eu não descrevi. Permissão do navegador é contrato de integração, não detalhe de implementação. Se fosse refazer, acrescentaria um **P5**: "gere os testes entre o que a Sync API responde e o schema (e as permissões) que a API do navegador exige".

## Conclusão em três linhas

- A IA não foi preguiçosa; ela foi **genérica**. O ganho veio de ancorar no mecanismo real e proibir invenção.
- Prompt é **plano de cobertura**: o que você não nomeia, não é testado — foi assim que descobri a especificação incompleta e a permissão que faltava.
- Transcript bruto vale mais que memória: eu tinha escrito "a v1 vai gerar teste raso" nas minhas anotações, rodei de verdade, e **três das quatro previsões estavam erradas**. Sem registrar a resposta crua, eu continuaria contando a história errada no fórum.
