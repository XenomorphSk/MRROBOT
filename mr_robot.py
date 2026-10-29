#!/usr/bin/env python3
"""
MR. ROBOT - agente local (v0.3)
Cerebro: Ollama (modelo pequeno) rodando offline.
Protocolo ReAct: o modelo emite UMA acao em JSON por vez; o harness executa e
devolve a observacao real. Mais robusto para modelos pequenos que o tool-calling nativo.

Dependencia unica:  pip install requests  (ou nem isso: usa urllib da stdlib)
Uso:                python3 mr_robot.py
Modo pentest:       python3 mr_robot.py --pentest
"""

import itertools
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request
import urllib.error

# ----------------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------------
OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = os.environ.get("MRROBOT_MODEL", "qwen2.5-coder:7b")
WORKDIR = os.environ.get("MRROBOT_WORKDIR", os.getcwd())
MODE = os.environ.get("MRROBOT_MODE", "ask")   # ask = confirma comando; auto = nao confirma
MAX_STEPS = 40

PENTEST = "--pentest" in sys.argv
SCOPE = []        # alvos autorizados, preenchidos no inicio da sessao pentest
REPORT_PATH = os.path.join(WORKDIR, "relatorio.md")

C = {
    "red": "\033[91m", "grn": "\033[92m", "ylw": "\033[93m",
    "blu": "\033[94m", "cyn": "\033[96m", "mag": "\033[95m",
    "dim": "\033[2m", "rst": "\033[0m",
}

ICONE = {
    "escrever_arquivo": "✎ escrevendo",
    "ler_arquivo":      "◇ lendo",
    "listar_dir":       "▤ listando",
    "rodar_comando":    "⚡ executando",
    "anotar_relatorio": "✚ anotando no relatorio",
}

# ----------------------------------------------------------------------------
# Prompts
# ----------------------------------------------------------------------------
PROTOCOLO = """Voce age exclusivamente emitindo UMA acao por vez, em JSON puro, assim:

{"pensamento": "o que estou fazendo e por que, em uma frase", "acao": "nome_da_ferramenta", "args": {...}}

Ferramentas disponiveis:
- escrever_arquivo  args: {"caminho": "...", "conteudo": "..."}
- ler_arquivo       args: {"caminho": "..."}
- listar_dir        args: {"caminho": "..."}   (caminho opcional)
- rodar_comando     args: {"comando": "..."}

Regras do protocolo:
- Responda SEMPRE com um unico objeto JSON e nada mais. Sem texto fora do JSON.
- Depois de cada acao, voce recebe uma OBSERVACAO com o resultado real. Use ela.
- Trabalhe em passos pequenos: uma coisa de cada vez, verificando o resultado antes de seguir.
- Sempre teste o que escrever, rodando. Nunca assuma que funcionou.
- Se der erro, leia a observacao, conserte e tente de novo.
- NUNCA repita um comando que ja rodou com sucesso. Cada passo deve avancar, nao repetir.
- Em scans, use flags verbosas (ex: nmap -v) e LEIA a saida real na OBSERVACAO antes de
  decidir o proximo passo. Nao invente resultado: se a saida nao mostra, voce nao sabe.
- Para rodar comando de shell, SEMPRE use {"acao": "rodar_comando", "args": {"comando": "..."}}.
  Nunca ponha o comando direto no campo "acao".
- Ao criar arquivos, use SEMPRE caminhos relativos simples (ex: "index.html", "src/app.py").
  Nunca use caminhos absolutos como /var/www/ ou /home/. Tudo e criado na pasta de trabalho atual.
- Quando a tarefa estiver 100% feita E verificada, em vez de JSON responda em texto normal
  comecando com "CONCLUIDO:" seguido de um resumo curto do que foi feito e verificado.
"""

BASE_PERSONA = """Voce e o MR. ROBOT, agente de pesquisa local especializado em
ciberseguranca, fisica, quimica e biologia, rodando offline no Kali Linux do operador,
um profissional de seguranca. Seja direto e tecnico.
"""

PENTEST_PERSONA = """Voce e o MR. ROBOT em MODO PENTEST, um assistente de teste de intrusao
autorizado, rodando no Kali Linux de um profissional de seguranca.

ESCOPO AUTORIZADO (unicos alvos que voce pode tocar): {scope}

Regras inviolaveis:
- Voce SO interage com hosts/dominios/IPs dentro do escopo acima. Qualquer pedido de acao
  contra algo fora do escopo: recuse e avise o operador.
- Metodologia, um passo de cada vez: (1) recon passivo, (2) enumeracao de servicos/portas,
  (3) fingerprint de tecnologias, (4) descoberta de conteudo, (5) identificacao de vulns,
  (6) validacao controlada com evidencia. Pare e relate antes de qualquer acao destrutiva.
- Ferramentas tipicas do Kali que voce pode orquestrar via rodar_comando: nmap, whatweb,
  wafw00f, gobuster, ffuf, nikto, nuclei, sqlmap (com flags conservadoras).
- Anote cada achado relevante com a ferramenta anotar_relatorio enquanto trabalha.
- Prefira flags nao-agressivas por padrao. Nada de forca bruta pesada ou DoS.

Alem das ferramentas normais, voce tem:
- anotar_relatorio  args: {{"titulo": "...", "conteudo": "..."}}  (acrescenta ao relatorio)
"""

# ----------------------------------------------------------------------------
# Spinner
# ----------------------------------------------------------------------------
# frases no estilo fsociety/Elliot (originais, nao copiadas do roteiro)
FRASES = [
    "hello, friend. procurando a brecha",
    "todo sistema tem um bug. esse nao e diferente",
    "controle e so uma ilusao bem codada",
    "ninguem e invisivel, so mal procurado",
    "a falha nunca esta no codigo, esta em quem confiou nele",
    "seguindo os pacotes ate onde eles nao deviam ir",
    "paciencia. o exploit certo aparece pra quem espera",
    "decompondo a mentira em binario",
    "eles deixaram uma porta aberta. sempre deixam",
    "o root e so o comeco da conversa",
    "lendo o que o alvo nao queria contar",
    "a rede sussurra. so precisa saber ouvir",
    "cada resposta do servidor e uma confissao",
    "montando o mapa que eles tentaram esconder",
    "nao invado. eu so entro por onde esqueceram de fechar",
]


class Spinner:
    def __init__(self, texto="raciocinando"):
        self.texto = texto
        self._stop = threading.Event()
        self._t = None

    def _girar(self):
        import random
        frase = random.choice(FRASES)
        trocou = time.time()
        for frame in itertools.cycle("⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"):
            if self._stop.is_set():
                break
            # troca a frase a cada ~4s pra ela nao ficar estatica em passos longos
            if time.time() - trocou > 4:
                frase = random.choice(FRASES)
                trocou = time.time()
                sys.stdout.write("\r" + " " * 70 + "\r")
            sys.stdout.write(f"\r{C['red']}{frame}{C['rst']} {C['dim']}{frase}...{C['rst']} ")
            sys.stdout.flush()
            time.sleep(0.08)

    def __enter__(self):
        self._t = threading.Thread(target=self._girar, daemon=True)
        self._t.start()
        return self

    def __exit__(self, *a):
        self._stop.set()
        if self._t:
            self._t.join()
        sys.stdout.write("\r" + " " * 70 + "\r")
        sys.stdout.flush()

# ----------------------------------------------------------------------------
# Ferramentas
# ----------------------------------------------------------------------------
def _safe_path(caminho):
    return caminho if os.path.isabs(caminho) else os.path.abspath(os.path.join(WORKDIR, caminho))


def _path_na_pasta(caminho):
    """Resolve o caminho SEMPRE dentro do WORKDIR. Bloqueia escrita fora da pasta de trabalho."""
    base = os.path.abspath(WORKDIR)
    # caminho absoluto ou com .. e reancorado pelo basename dentro do workdir
    alvo = os.path.abspath(os.path.join(base, caminho))
    if os.path.commonpath([base, alvo]) != base:
        alvo = os.path.join(base, os.path.basename(caminho.rstrip("/")) or "saida")
    return alvo


# --- portao de escopo: enforcement em codigo, nao no prompt ---------------
_FILE_EXT = {"md", "py", "txt", "json", "sh", "log", "csv", "xml", "html",
             "js", "conf", "yaml", "yml", "cfg", "bin", "sha256", "c", "cpp", "go"}


def _norm_host(h):
    h = re.sub(r"^\w+://", "", h.strip()).split("/")[0]
    m = re.match(r"^(.*):(\d+)$", h)   # tira :porta
    if m:
        h = m.group(1)
    return h.strip("[]").lower()


def _permitidos():
    p = {"localhost", "127.0.0.1", "::1"}
    for s in SCOPE:
        p.add(_norm_host(s))
    return p


def _candidatos_host(cmd):
    cands = set()
    for m in re.findall(r"https?://([^\s/:'\"]+)", cmd):         # hosts em URLs
        cands.add(m)
    for m in re.findall(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", cmd):    # IPv4
        cands.add(m)
    for m in re.findall(r"\b(?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}\b", cmd):  # dominios
        if m.rsplit(".", 1)[-1].lower() not in _FILE_EXT:       # ignora nomes de arquivo
            cands.add(m)
    return cands


def _fora_de_escopo(cmd):
    if not SCOPE:                       # sem escopo (modo pesquisa): sem restricao
        return []
    permitidos = _permitidos()
    return [c for c in _candidatos_host(cmd) if _norm_host(c) not in permitidos]


def tool_escrever_arquivo(caminho, conteudo):
    p = _path_na_pasta(caminho)   # sempre dentro do WORKDIR
    try:
        os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(conteudo)
        aviso = ""
        if os.path.basename(p) != os.path.basename(caminho.rstrip("/")):
            aviso = " (caminho reancorado para dentro da pasta de trabalho)"
        return f"OK: {len(conteudo)} bytes em {p}{aviso}"
    except Exception as e:
        return f"ERRO ao escrever em {p}: {e}. Use um caminho relativo dentro da pasta de trabalho."


def tool_ler_arquivo(caminho):
    try:
        with open(_path_na_pasta(caminho), "r", encoding="utf-8", errors="replace") as f:
            return f.read()[:20000]
    except Exception as e:
        return f"ERRO ao ler: {e}"


def tool_listar_dir(caminho="."):
    try:
        itens = sorted(os.listdir(_safe_path(caminho)))
        return "\n".join(itens) if itens else "(vazio)"
    except Exception as e:
        return f"ERRO: {e}"


def tool_rodar_comando(comando):
    # PORTAO DE ESCOPO: bloqueia host fora do escopo mesmo em modo auto.
    fora = _fora_de_escopo(comando)
    if fora:
        print(f"\n{C['red']}[BLOQUEADO: fora do escopo]{C['rst']} {C['cyn']}{', '.join(fora)}{C['rst']}")
        return (f"BLOQUEADO: o comando referencia host(s) fora do escopo autorizado: "
                f"{', '.join(fora)}. Escopo permitido: {', '.join(SCOPE)}. "
                f"Voce so pode agir sobre o escopo. Reformule a acao usando apenas o alvo autorizado.")

    if MODE == "ask":
        print(f"\n{C['ylw']}[rodar]{C['rst']} {C['cyn']}{comando}{C['rst']}")
        resp = input(f"{C['dim']}Enter=exec | n=recusar | a=sempre: {C['rst']}").strip().lower()
        if resp == "n":
            return "RECUSADO pelo operador. Proponha outra abordagem."
        if resp == "a":
            globals()["MODE"] = "auto"
    try:
        r = subprocess.run(comando, shell=True, cwd=WORKDIR, capture_output=True,
                           text=True, timeout=300)
        out = (r.stdout or "") + (("\n[stderr]\n" + r.stderr) if r.stderr else "")
        return f"[exit {r.returncode}]\n{(out.strip() or '(sem saida)')[:15000]}"
    except subprocess.TimeoutExpired:
        return "ERRO: comando passou de 300s e foi interrompido."
    except KeyboardInterrupt:
        return "INTERROMPIDO pelo operador (Ctrl-C). Comando abortado, de volta ao controle."
    except Exception as e:
        return f"ERRO: {e}"


def tool_anotar_relatorio(titulo, conteudo):
    ts = time.strftime("%Y-%m-%d %H:%M")
    with open(REPORT_PATH, "a", encoding="utf-8") as f:
        f.write(f"\n## {titulo}\n_{ts}_\n\n{conteudo}\n")
    return f"OK: anotado em {REPORT_PATH}"


DISPATCH = {
    "escrever_arquivo": tool_escrever_arquivo,
    "ler_arquivo": tool_ler_arquivo,
    "listar_dir": tool_listar_dir,
    "rodar_comando": tool_rodar_comando,
    "anotar_relatorio": tool_anotar_relatorio,
}

# ----------------------------------------------------------------------------
# Ollama
# ----------------------------------------------------------------------------
def ollama_chat(messages):
    payload = {
        "model": MODEL,
        "messages": messages,
        "stream": False,
        "options": {"temperature": 0.2, "num_thread": 8},
        "keep_alive": "30m",
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(OLLAMA_URL, data=data,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=900) as resp:
            return json.loads(resp.read().decode("utf-8"))["message"]
    except urllib.error.URLError:
        print(f"{C['red']}Sem conexao com o Ollama em {OLLAMA_URL}. Rode 'ollama serve'.{C['rst']}")
        sys.exit(1)


# ----------------------------------------------------------------------------
# Extrator de acao ReAct: acha o primeiro JSON valido no texto do modelo
# ----------------------------------------------------------------------------
def extrair_acao(texto):
    # tenta blocos ```json ... ``` primeiro, depois qualquer {...}
    candidatos = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", texto, re.DOTALL)
    candidatos += re.findall(r"(\{(?:[^{}]|\{[^{}]*\})*\})", texto, re.DOTALL)
    for c in candidatos:
        try:
            obj = json.loads(c)
        except Exception:
            continue
        acao = obj.get("acao") or obj.get("name") or obj.get("tool")
        args = obj.get("args") or obj.get("arguments") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except Exception:
                args = {}
        if acao:
            return {"pensamento": obj.get("pensamento", ""), "acao": acao, "args": args}
    return None


# ----------------------------------------------------------------------------
# Laco do agente
# ----------------------------------------------------------------------------
def agente(tarefa, messages):
    messages.append({"role": "user", "content": tarefa})
    historico_acoes = []
    sem_acao = 0

    for passo in range(MAX_STEPS):
        try:
            with Spinner(f"raciocinando (passo {passo + 1})"):
                msg = ollama_chat(messages)
        except KeyboardInterrupt:
            print(f"\n{C['ylw']}interrompido. de volta ao prompt.{C['rst']}")
            return
        conteudo = (msg.get("content") or "").strip()
        messages.append({"role": "assistant", "content": conteudo})

        # terminou?
        if conteudo.upper().startswith("CONCLUIDO") or "CONCLUIDO:" in conteudo.upper()[:40]:
            print(f"\n{C['grn']}{conteudo}{C['rst']}")
            return

        acao = extrair_acao(conteudo)
        if not acao:
            # modelo falou sem emitir acao
            sem_acao += 1
            if sem_acao >= 2:
                # travou sem agir duas vezes: provavelmente ja terminou. Encerra mostrando o texto.
                print(f"\n{C['grn']}{conteudo or '(tarefa finalizada)'}{C['rst']}")
                print(f"{C['dim']}(encerrado: sem mais acoes){C['rst']}")
                return
            print(f"{C['dim']}(resposta sem acao, reconduzindo){C['rst']}")
            messages.append({"role": "user", "content":
                "Se a tarefa acabou, responda comecando com 'CONCLUIDO:' e um resumo. "
                "Se ainda falta algo, responda APENAS com um objeto JSON de acao."})
            continue
        sem_acao = 0

        if acao["pensamento"]:
            print(f"{C['mag']}  ~ {acao['pensamento']}{C['rst']}")

        fn = acao["acao"]
        args = acao["args"]

        # correcao: modelo as vezes poe o comando inteiro no campo 'acao'.
        # se 'fn' nao e uma ferramenta conhecida mas parece um comando, redireciona.
        if fn not in DISPATCH:
            if " " in fn or "/" in fn:
                args = {"comando": fn}
                fn = "rodar_comando"
            else:
                messages.append({"role": "user", "content":
                    f"A ferramenta '{fn}' nao existe. Use uma destas: {', '.join(DISPATCH)}. "
                    f"Para rodar comando de shell, use rodar_comando com args.comando."})
                continue

        # detector de loop: mesma acao+args repetida trava o agente
        assinatura = f"{fn}:{json.dumps(args, sort_keys=True)}"
        historico_acoes.append(assinatura)
        if historico_acoes.count(assinatura) >= 3:
            print(f"{C['red']}  loop detectado: a mesma acao se repetiu. Parando.{C['rst']}")
            messages.append({"role": "user", "content":
                "Voce repetiu a mesma acao varias vezes sem progredir. PARE de repetir. "
                "Leia a ultima OBSERVACAO com atencao, e ou faca algo diferente, ou "
                "responda 'CONCLUIDO:' com o que ja descobriu."})
            historico_acoes.clear()
            continue
        alvo = args.get("caminho") or args.get("comando") or args.get("titulo") or ""
        print(f"{C['blu']}{ICONE.get(fn, '• ' + fn)}{C['rst']} {C['cyn']}{str(alvo)[:70]}{C['rst']}")

        handler = DISPATCH.get(fn)
        resultado = handler(**args) if handler else f"ERRO: ferramenta '{fn}' nao existe."

        primeira = str(resultado).strip().splitlines()[0] if str(resultado).strip() else ""
        print(f"  {C['dim']}└ {primeira[:80]}{C['rst']}")

        messages.append({"role": "user", "content": f"OBSERVACAO:\n{resultado}"})

    print(f"{C['red']}Limite de {MAX_STEPS} passos. Parei por seguranca.{C['rst']}")


def banner():
    modo_txt = f"{C['red']}PENTEST{C['rst']}" if PENTEST else "pesquisa"
    print(f"""{C['red']}
    ███╗   ███╗██████╗     ██████╗  ██████╗ ██████╗  ██████╗ ████████╗
    ████╗ ████║██╔══██╗    ██╔══██╗██╔═══██╗██╔══██╗██╔═══██╗╚══██╔══╝
    ██╔████╔██║██████╔╝    ██████╔╝██║   ██║██████╔╝██║   ██║   ██║
    ██║╚██╔╝██║██║  ██║    ██║  ██║╚██████╔╝██████╔╝╚██████╔╝   ██║
    ╚═╝     ╚═╝╚═╝  ╚═╝    ╚═╝  ╚═╝ ╚═════╝ ╚═════╝  ╚═════╝    ╚═╝{C['rst']}
    {C['dim']}cerebro: {MODEL}  |  modo: {MODE}  |  perfil: {modo_txt}{C['rst']}
    {C['dim']}hello, friend. digite a tarefa, ou 'sair'.{C['rst']}
""")


def iniciar_escopo():
    print(f"{C['ylw']}MODO PENTEST. Confirme que voce tem autorizacao para testar os alvos.{C['rst']}")
    alvos = input(f"{C['cyn']}Escopo autorizado (hosts/IPs separados por virgula): {C['rst']}").strip()
    if not alvos:
        print(f"{C['red']}Sem escopo definido. Saindo.{C['rst']}")
        sys.exit(0)
    SCOPE.extend([a.strip() for a in alvos.split(",") if a.strip()])
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write(f"# Relatorio MR. ROBOT\n\nEscopo: {', '.join(SCOPE)}\n"
                f"Inicio: {time.strftime('%Y-%m-%d %H:%M')}\n")
    print(f"{C['grn']}Escopo travado: {', '.join(SCOPE)}  |  relatorio em {REPORT_PATH}{C['rst']}")


def main():
    if PENTEST:
        iniciar_escopo()
        system = BASE_PERSONA + PENTEST_PERSONA.format(scope=", ".join(SCOPE)) + PROTOCOLO
    else:
        system = BASE_PERSONA + PROTOCOLO
    banner()
    messages = [{"role": "system", "content": system}]
    while True:
        try:
            tarefa = input(f"\n{C['red']}mr.robot>{C['rst']} ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nbye, friend.")
            break
        if tarefa.lower() in ("sair", "exit", "quit"):
            print("bye, friend.")
            break
        if tarefa:
            agente(tarefa, messages)


if __name__ == "__main__":
    main()
