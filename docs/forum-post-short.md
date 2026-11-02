# Testes de integração com GenAI: o que aprendi no Tomatto (versão curta, ~750 palavras)

Repositório: https://github.com/CarlosERM/tomatto

## O projeto

O **Tomatto** bloqueia sites sem interface. São três peças conversando por HTTP: a **Manager API** (`:3001`) guarda os domínios no SQLite e, a cada mudança, empurra a lista inteira para a **Sync API** (`:3002`), com um número de versão que só cresce; a Sync entrega essa lista usando cache (`304 Not Modified` quando nada mudou); uma **extensão Chrome (MV3)** consulta a lista a cada minuto e aplica o bloqueio.

O exercício pedia gerar os **testes de integração** — os que conferem se as peças conversam direito — com ajuda de uma GenAI, usando quatro tipos de prompt: contrato (a partir do OpenAPI), cenários ponta a ponta, QA adversarial entre serviços e geração de dados de teste. Cada prompt tem versão 1 (ingênua) e versão 2 (revisada). Rodei as duas: **8 execuções**, modelo local (Qwen3.8 Flash Next no LM Studio), cada uma em conversa zerada, sem acesso ao código. Respostas brutas em [`generated-tests/`](../generated-tests/), sem edição.

## O que eu esperava vs. o que aconteceu

Eu achava que a IA ia gerar teste raso ("testa se retorna 200"). Não foi isso. Em três dos quatro prompts, a versão 1 veio detalhada, bem formatada e tecnicamente correta — no P1 ela devolveu pytest pronto para rodar, validando o JSON contra o schema da spec, cobrindo os sete endpoints sem inventar nenhum.

O problema foi **falta de ancoragem**: qualidade gasta em coisas que não existem no meu sistema. No P2 ela pediu teste de autenticação com token, de bloqueio que expira, de sincronização por delta e de paginação — nada disso existe aqui. E entre trinta cenários nunca citou os três mecanismos que seguram a integração: o push a cada mudança, a versão monotônica e o campo `sync_status="pending"`.

| Prompt | v1 (ingênua) | v2 (revisada) |
|---|---|---|
| P1 contrato | pytest executável, mas mudo sobre rejeição de versão antiga; usava `pytest.skip` se a Sync caísse — integração quebrada ficaria verde | 19 linhas, uma por promessa, incluindo as quatro regras entre os serviços |
| P2 cenários | ~30 cenários, cheios de features inventadas | 7 cenários que sempre tocam as duas APIs e dizem qual costura testam; zero invenção |
| P3 adversarial | ~50 casos genéricos (JWT, gzip bomb, IDOR), nenhum alcançável num demo local | 14 casos entre os dois serviços, com o sintoma que o usuário veria |
| P4 dados | Aqui a previsão acertou: 20 nomes de marca e zero caso limite | 12 + 8 linhas exatas, punycode correto (conferi contra a lib `idna`) |

Ou seja: não adiantou pedir "testes melhores". Adiantou **descrever o mecanismo e proibir saída fora dele**.

## Dois achados que valeram mais que os testes

**O erro estava no meu prompt, e a IA resolveu calada.** No P1 coloquei duas regras que se contradiziam: uma pedia teste de rejeição de snapshot antigo (que retorna `409`), outra proibia status code fora da spec — e minha spec não documenta o `409`. A IA desobedeceu a segunda regra em silêncio. O defeito real é especificação incompleta, não prompt.

**Um cenário gerado previu um bug de verdade.** Saiu no P2 que, durante queda da Sync, a extensão continua recebendo `304` contra versão velha e precisa manter a lista antiga ativa. Dias depois esbarrei nisso: o caminho do `304` saía antes da lógica que atualizava as regras — nada mudava e nenhum log aparecia.

## O que nenhum prompt cobriu

Nenhum falou do **consumidor final**, a extensão — e foi lá que o projeto travou por dias. As regras eram registradas sem erro, a contagem batia, o dump mostrava tudo certo, e nada era bloqueado: site abria normal, sem log nem exceção. A causa é que a permissão `declarativeNetRequest` cobre automaticamente só as regras `allow`, `allowAllRequests` e `block`; regra de **redirecionamento** exige `host_permissions` para os sites afetados — sem isso o Chrome aceita a regra mas nunca aplica.

A GenAI testou muito bem cada costura que eu descrevi e ignorou as que eu não descrevi. Permissão de navegador é contrato de integração, não detalhe de implementação.

## Em três linhas

- A IA não foi preguiçosa, foi **genérica**: o ganho veio de ancorar no mecanismo real.
- Prompt é **plano de cobertura** — o que você não nomeia não é testado.
- Registrar a resposta bruta me obrigou a admitir que **3 das 4 previsões** que eu tinha escrito sobre a v1 estavam erradas.
