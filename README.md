# MR. ROBOT

Agente de pesquisa local, offline e totalmente customizável, especializado em **cibersegurança, física, química e biologia**.

Roda um modelo de linguagem local (via [Ollama](https://ollama.com)) dentro de um laço de ferramentas no estilo Claude Code: o cérebro decide uma ação, o harness executa de verdade na sua máquina, lê o resultado e corrige o rumo, até concluir. Sem custo de token, sem depender de nuvem, e portável no bolso.

```
    ███╗   ███╗██████╗     ██████╗  ██████╗ ██████╗  ██████╗ ████████╗
    ████╗ ████║██╔══██╗    ██╔══██╗██╔═══██╗██╔══██╗██╔═══██╗╚══██╔══╝
    ██╔████╔██║██████╔╝    ██████╔╝██║   ██║██████╔╝██║   ██║   ██║
    ██║╚██╔╝██║██╔══██╗    ██╔══██╗██║   ██║██╔══██╗██║   ██║   ██║
    ██║ ╚═╝ ██║██║  ██║    ██║  ██║╚██████╔╝██████╔╝╚██████╔╝   ██║
    ╚═╝     ╚═╝╚═╝  ╚═╝    ╚═╝  ╚═╝ ╚═════╝ ╚═════╝  ╚═════╝    ╚═╝
```

> *hello, friend.*

---

## O que ele faz

- **Escreve e executa código**, de scripts simples a aplicações, testando o que produz.
- **Revisa código** em busca de padrões de vulnerabilidade (SQLi, XSS, command injection, path traversal, etc.).
- **Orquestra ferramentas do Kali** (nmap, whatweb, nuclei, sqlmap e outras) num fluxo de recon e enumeração.
- **Raciocínio visível**: mostra o que está pensando a cada passo.
- **Modo pentest** com escopo autorizado travado em código e geração de relatório.

### O que ele NÃO é

Seja honesto com a expectativa: com um cérebro pequeno rodando local, o MR. ROBOT é um **copiloto semiautônomo**, não um hacker autônomo. Ele automatiza a parte repetitiva (recon, enumeração, rascunho de scripts) e levanta suspeitas; a análise fina e a exploração criativa continuam sendo suas. Caçar vulnerabilidade inédita de ponta a ponta sozinho está além de um modelo local, e também dos modelos de fronteira hoje.

---

## Requisitos

- Linux (desenvolvido e testado em Kali)
- Python 3.9+
- [Ollama](https://ollama.com) instalado
- ~5 GB de RAM livre para um modelo de 7B (ou ~2,5 GB para um modelo de 3-4B)
- Ferramentas de recon do Kali, conforme o uso (nmap, nuclei, sqlmap, etc.)

---

## Instalação

```bash
git clone <seu-repo>/mr-robot.git   # ou baixe os arquivos
cd mr-robot
bash install.sh
```

O instalador:

1. instala as dependências (Python, requests, nmap, Ollama);
2. cria o comando global `mrrobot`;
3. agenda uma atualização semanal (templates do nuclei, modelos, e o próprio script via git se houver repo).

Depois, abra um novo terminal (ou `source ~/.zshrc`) e baixe um cérebro:

```bash
ollama pull qwen2.5-coder:7b
```

---

## Uso

O comando usa a **pasta atual** como diretório de trabalho. Abra o terminal onde quiser que ele gere arquivos:

```bash
cd ~/meu-projeto
mrrobot
```

Exemplo de tarefa:

```
mr.robot> crie um scanner de portas com asyncio, rode contra 127.0.0.1 nas portas 1-1000 e me mostre o resultado
```

### Modo pentest

```bash
mrrobot --pentest
```

Ele pede o **escopo autorizado** no início e o trava. Comandos contra qualquer host fora do escopo são **bloqueados no código**, mesmo no modo automático. Os achados vão para `relatorio.md`.

```
Escopo autorizado (hosts/IPs separados por virgula): 127.0.0.1, meulab.local
mr.robot> faça o recon do alvo
```

---

## Configuração

Via variáveis de ambiente:

| Variável           | Padrão                | Função                                             |
|--------------------|-----------------------|----------------------------------------------------|
| `MRROBOT_MODEL`    | `qwen2.5-coder:7b`    | modelo do Ollama usado como cérebro                |
| `MRROBOT_WORKDIR`  | pasta atual           | diretório de trabalho                              |
| `MRROBOT_MODE`     | `ask`                 | `ask` confirma cada comando; `auto` não confirma   |
| `OLLAMA_KEEP_ALIVE`| `30m`                 | tempo que o modelo fica residente na RAM           |

Exemplo, usando um cérebro mais leve e rápido:

```bash
MRROBOT_MODEL=phi4-mini mrrobot
```

---

## Como funciona

Quatro camadas:

1. **Cérebro** — modelo local via Ollama (ex.: Qwen2.5-Coder).
2. **Laço de ferramentas** — protocolo ReAct: o modelo emite uma ação em JSON, o harness executa e devolve a observação real. Mais robusto que tool-calling nativo para modelos pequenos.
3. **Raciocínio + decomposição** — um passo de cada vez, verificando cada resultado antes de seguir. A ordem dos passos vive na estrutura do código, não no peso do modelo.
4. **Especialização** — persona e metodologia por system prompt; conhecimento que muda (CVEs, técnicas) entra por ferramentas atualizadas e, futuramente, RAG.

### Ferramentas disponíveis ao agente

| Ferramenta          | Ação                                        |
|---------------------|---------------------------------------------|
| `escrever_arquivo`  | cria ou sobrescreve um arquivo              |
| `ler_arquivo`       | lê o conteúdo de um arquivo                 |
| `listar_dir`        | lista um diretório                          |
| `rodar_comando`     | executa um comando de shell                 |
| `anotar_relatorio`  | acrescenta um achado ao relatório (pentest) |

---

## Segurança e responsabilidade

- **Humano no loop por padrão.** No modo `ask`, cada comando pede confirmação antes de rodar.
- **Escopo enforçado em código.** No modo pentest, o alvo autorizado é travado e hosts fora dele são bloqueados antes da execução.
- **Autorização é sua responsabilidade.** Só use contra sistemas que você tem permissão explícita para testar (seu lab, programa de bug bounty dentro do escopo, ou contrato assinado). A trava de escopo evita drift acidental; ela não substitui a autorização.
- **O modelo pode errar e inventar.** Modelos pequenos às vezes "alucinam" achados. Confie sempre na saída crua da ferramenta, nunca no resumo narrado pelo agente.

---

## Roadmap

- [ ] RAG sobre base de conhecimento de segurança (CVEs, writeups, payloads)
- [ ] Travar o diretório de trabalho na geração de arquivos
- [ ] Suporte a modelo de raciocínio quando houver RAM/hardware
- [ ] Alvo de laboratório vulnerável incluído para calibração
- [ ] Auto-update via repositório git

---

## Licença

Defina a licença do projeto (ex.: MIT).

---

*Projeto pessoal. Use com responsabilidade.*
