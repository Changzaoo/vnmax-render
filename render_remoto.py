# -*- coding: utf-8 -*-
"""Renderiza, numa máquina Linux (VM ou Colab), o pacote de um país feito por
empacotar.py. Só biblioteca padrão do Python; precisa de node + hyperframes +
ffmpeg (bootstrap.sh instala).

  python3 render_remoto.py BR.tar.gz                    tudo o que está no pacote
  python3 render_remoto.py BR.tar.gz --workers 7        processos do Chrome (padrão: núcleos − 1)
  python3 render_remoto.py BR.tar.gz --capitulos 2,5    só esses
  python3 render_remoto.py BR.tar.gz --saida /x/BR      onde vai a saída (ex.: pasta do Google Drive)
  python3 render_remoto.py BR.tar.gz --dry-run          só lista o que faria
  opções: --base ~/vnmax-render  --tmp <pasta com espaço>  --filme  --manter-mestre

Por capítulo (retomável: capítulo com saida/partes/cap-NN.json é pulado):
  1. hyperframes render → mudo.mp4 (até 3 tentativas: a GSAP vem da CDN)
  2. mix: mudo + audio.flac → capitulo.mp4 (CRF 20, loudnorm), igual ao --render daqui
  3. web: cap-NN.mp4 (≤ 95 MB, CRF 23→32), cap-NN.jpg (capa), cap-NN-previa.jpg
  4. grava saida/partes/cap-NN.json — o capítulo está salvo
No fim: indice.json (o mesmo formato do documentario_pais.py --web),
roteiro.json, capitulos.txt (marcas de capítulo do filme inteiro) e pronto.json.
Com --filme também junta <ISO>-uma-historia.mp4 (precisa de --manter-mestre).

NÃO publica: traga a pasta de saída de volta e rode, no Windows,
  python documentario_pais.py <ISO> --publicar --de <pasta trazida>"""
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import time

FPS = 24
PREVIA_PASSO, PREVIA_W, PREVIA_H, PREVIA_COLS = 5, 192, 108, 10   # = doc/documentario.py
SECO = False
LOG = None


def agora():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def diz(msg):
    linha = "[%s] %s" % (agora(), msg)
    print(linha, flush=True)
    if LOG and not SECO:
        with io.open(LOG, "a", encoding="utf-8") as f:
            f.write(linha + "\n")


def sh(cmd, cwd=None, env=None):
    if SECO:
        print("    $ %s%s" % ("(em %s) " % cwd if cwd else "", " ".join(cmd)), flush=True)
        return ""
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    if r.returncode:
        raise RuntimeError("falhou: %s\n%s\n%s" % (" ".join(cmd), r.stdout[-1500:], r.stderr[-2500:]))
    return r.stdout


def duracao(mp4):
    return float(sh(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", mp4]).strip() or 0)


def livre_gb(pasta):
    try:
        return shutil.disk_usage(pasta).free / 1e9
    except OSError:
        return -1


def nucleos():
    try:
        return len(os.sched_getaffinity(0))
    except AttributeError:
        return os.cpu_count() or 2


def hyperframes_bin(base):
    for c in (os.path.join(base, "node_modules", ".bin", "hyperframes"),
              os.path.join(base, "node_modules", ".bin", "hyperframes.cmd")):
        if os.path.exists(c):
            return [c]
    return ["npx.cmd" if os.name == "nt" else "npx", "--no-install", "hyperframes"]


def desempacotar(pacote, trabalho):
    """Extrai o pacote em trabalho/<ISO>/ (só se mudou). Aceita também uma
    pasta já extraída (com meta.json)."""
    if os.path.isdir(pacote):
        return pacote
    with tarfile.open(pacote, "r:*") as tar:
        meta = json.load(tar.extractfile("meta.json"))
        dst = os.path.join(trabalho, meta["iso"])
        marca = os.path.join(dst, ".pacote.json")
        sinal = dict(pacote=os.path.basename(pacote), tamanho=os.path.getsize(pacote), gerado=meta["gerado"])
        try:
            if json.load(io.open(marca, encoding="utf-8")) == sinal:
                return dst
        except Exception:
            pass
        if SECO:
            print("    extrairia %s em %s" % (pacote, dst))
            return None, meta
        os.makedirs(dst, exist_ok=True)
        diz("extraindo %s em %s …" % (pacote, dst))
        try:
            tar.extractall(dst, filter="data")
        except TypeError:   # Python sem o filtro (anterior às correções de 2023)
            for m in tar.getmembers():
                if m.name.startswith("/") or ".." in m.name.split("/"):
                    raise SystemExit("pacote com caminho suspeito: " + m.name)
            tar.extractall(dst)
        io.open(marca, "w", encoding="utf-8").write(json.dumps(sinal))
    return dst


def ler_meta(pacote):
    if os.path.isdir(pacote):
        return json.load(io.open(os.path.join(pacote, "meta.json"), encoding="utf-8"))
    with tarfile.open(pacote, "r:*") as tar:
        return json.load(tar.extractfile("meta.json"))


def folha_previa(mp4, destino, dur):
    n = int(dur // PREVIA_PASSO) + 1
    linhas = (n + PREVIA_COLS - 1) // PREVIA_COLS
    sh(["ffmpeg", "-y", "-v", "error", "-i", mp4, "-vf",
        "fps=1/%d,scale=%d:%d,tile=%dx%d" % (PREVIA_PASSO, PREVIA_W, PREVIA_H, PREVIA_COLS, linhas),
        "-frames:v", "1", "-q:v", "6", destino])
    return dict(arquivo=os.path.basename(destino), passo=PREVIA_PASSO, w=PREVIA_W, h=PREVIA_H, cols=PREVIA_COLS, n=n)


def copiar_seguro(src, dst):
    """Cópia para a saída (que pode ser o Drive): grava .parcial e renomeia."""
    if SECO:
        print("    copia %s → %s" % (src, dst))
        return
    tmp = dst + ".parcial"
    shutil.copyfile(src, tmp)
    os.replace(tmp, dst)


def capitulo(cap, proj, saida, hf, workers, env, manter):
    n = cap["n"]
    pasta = os.path.join(proj, "capitulos", cap["pasta"]) if proj else "<trabalho>/capitulos/" + cap["pasta"]
    parte = os.path.join(saida, "partes", "cap-%02d.json" % n)
    web_final = os.path.join(saida, "cap-%02d.mp4" % n)
    if os.path.exists(parte) and os.path.exists(web_final):
        diz("já pronto: %s" % cap["pasta"])
        return json.load(io.open(parte, encoding="utf-8"))
    t0 = time.time()
    prev = cap.get("dur_prevista") or 0
    diz("capítulo %s (%.1f min de vídeo) …" % (cap["pasta"], prev / 60))
    local = os.path.join(pasta, "_web") if proj else "<trabalho>/_web"
    if not SECO:
        os.makedirs(local, exist_ok=True)
    mestre = os.path.join(pasta, "capitulo.mp4")
    html = os.path.join(pasta, "index.html")
    if not SECO and os.path.exists(mestre) and os.path.getmtime(mestre) >= os.path.getmtime(html):
        diz("  capitulo.mp4 já existe — vai direto à versão web")
    else:
        for tentativa in range(3):
            try:
                sh(hf + ["render", "-o", "mudo.mp4", "-q", "high", "-f", str(FPS), "-w", str(workers)], cwd=pasta, env=env)
                break
            except RuntimeError as erro:
                if tentativa == 2:
                    raise
                diz("  render falhou (%s), tentando de novo…" % str(erro).strip().splitlines()[-1][:160])
        diz("  render ok em %.0f min; mix …" % ((time.time() - t0) / 60))
        audio = "audio.flac" if (SECO or os.path.exists(os.path.join(pasta, "audio.flac"))) else "audio.wav"
        sh(["ffmpeg", "-y", "-v", "error", "-i", "mudo.mp4", "-i", audio, "-map", "0:v", "-map", "1:a",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
            "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-shortest", "-movflags", "+faststart", "capitulo.mp4.tmp.mp4"], cwd=pasta, env=env)
        if not SECO:
            os.replace(os.path.join(pasta, "capitulo.mp4.tmp.mp4"), mestre)
            os.remove(os.path.join(pasta, "mudo.mp4"))
    # versão web (igual a documentario_pais.versao_web)
    nome = "cap-%02d.mp4" % n
    dst = os.path.join(local, nome)
    for crf in (23, 26, 29, 32):
        sh(["ffmpeg", "-y", "-v", "error", "-i", mestre, "-c:v", "libx264", "-preset", "slow", "-crf", str(crf),
            "-profile:v", "high", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", dst], env=env)
        if SECO or os.path.getsize(dst) < 95 * 1024 * 1024:
            break
    capa = "cap-%02d.jpg" % n
    sh(["ffmpeg", "-y", "-v", "error", "-ss", "4", "-i", mestre, "-frames:v", "1", "-vf", "scale=640:-1", "-q:v", "4",
        os.path.join(local, capa)], env=env)
    dur = 0.0 if SECO else duracao(dst)
    previa = folha_previa(dst, os.path.join(local, "cap-%02d-previa.jpg" % n), dur) if not SECO else \
        (sh(["ffmpeg", "…", "tile=…", "cap-%02d-previa.jpg" % n]) or {})
    entrada = dict(n=n, romano=cap["romano"], titulo=cap["titulo"], de=cap["de"], ate=cap["ate"], momentos=cap["momentos"],
                   arquivo=nome, capa=capa, duracao=round(dur, 1),
                   mb=round(os.path.getsize(dst) / 1048576, 1) if not SECO else 0, marcas=cap["marcas"], previa=previa)
    if not SECO:
        os.makedirs(os.path.join(saida, "partes"), exist_ok=True)
    for f in (nome, capa, "cap-%02d-previa.jpg" % n):
        copiar_seguro(os.path.join(local, f), os.path.join(saida, f))
    if not SECO:
        tmp = parte + ".parcial"
        io.open(tmp, "w", encoding="utf-8").write(json.dumps(entrada, ensure_ascii=False))
        os.replace(tmp, parte)
        if hasattr(os, "sync"):
            os.sync()
        shutil.rmtree(local, ignore_errors=True)
        if not manter:
            os.remove(mestre)
    else:
        print("    grava %s" % parte)
    diz("  ok %s: %.1f MB, %.1f min, em %.0f min de máquina" % (cap["pasta"], entrada["mb"], dur / 60, (time.time() - t0) / 60))
    return entrada


def fechar(meta, proj, saida, filme):
    """indice.json, roteiro.json, capitulos.txt, pronto.json com o que há em partes/."""
    partes = os.path.join(saida, "partes")
    feitos = {}
    if os.path.isdir(partes):
        for f in sorted(os.listdir(partes)):
            if f.startswith("cap-") and f.endswith(".json"):
                e = json.load(io.open(os.path.join(partes, f), encoding="utf-8"))
                feitos[e["n"]] = e
    todos = meta.get("todos") or [c["n"] for c in meta["capitulos"]]
    faltam = [n for n in todos if n not in feitos]
    indice = dict(titulo=meta["titulo"], pais=meta["iso"], atualizado=int(time.time()),
                  capitulos=[feitos[n] for n in sorted(feitos)])
    io.open(os.path.join(saida, "indice.json"), "w", encoding="utf-8").write(json.dumps(indice, ensure_ascii=False))
    if proj:
        copiar_seguro(os.path.join(proj, "roteiro.json"), os.path.join(saida, "roteiro.json"))
    # marcas do filme inteiro (YouTube etc.) — só faz sentido com todos os capítulos
    marcas, t = [], 0.0
    for n in sorted(feitos):
        e = feitos[n]
        marcas.append("%d:%02d:%02d Capítulo %s — %s" % (t // 3600, (t % 3600) // 60, t % 60, e["romano"], e["titulo"]))
        t += e["duracao"]
    io.open(os.path.join(saida, "capitulos.txt"), "w", encoding="utf-8").write(
        "\n".join(marcas) + "\n" + ("" if not faltam else "# INCOMPLETO: faltam os capítulos %s\n" % faltam))
    pronto = dict(iso=meta["iso"], completo=not faltam, feitos=sorted(feitos), faltam=faltam, minutos=round(t / 60, 1),
                  pacote_gerado=meta.get("gerado"), terminado=agora())
    io.open(os.path.join(saida, "pronto.json"), "w", encoding="utf-8").write(json.dumps(pronto, ensure_ascii=False, indent=1))
    if filme and not faltam and proj:
        lista = []
        for c in sorted(meta["capitulos"], key=lambda c: c["n"]):
            mp4 = os.path.join(proj, "capitulos", c["pasta"], "capitulo.mp4")
            if not os.path.exists(mp4):
                diz("--filme: falta %s (rode com --manter-mestre)" % mp4)
                break
            lista.append("file '%s'" % mp4)
        else:
            arq = os.path.join(proj, "lista.txt")
            io.open(arq, "w", encoding="utf-8").write("\n".join(lista))
            sh(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", arq, "-c", "copy", "-movflags", "+faststart",
                os.path.join(saida, "%s-uma-historia.mp4" % meta["iso"])])
    diz("saída: %s — %s" % (saida, "COMPLETA (%d capítulos, %.0f min)" % (len(feitos), t / 60) if not faltam
                           else "parcial: faltam %s" % faltam))
    return pronto


def main():
    global SECO, LOG
    sys.stdout.reconfigure(encoding="utf-8")
    a = sys.argv[1:]
    if not a or a[0].startswith("-"):
        raise SystemExit(__doc__)

    def opc(nome, padrao=None):
        return a[a.index(nome) + 1] if nome in a else padrao
    pacote = os.path.abspath(os.path.expanduser(a[0]))
    SECO = "--dry-run" in a
    base = os.path.abspath(os.path.expanduser(opc("--base", "~/vnmax-render")))
    workers = int(opc("--workers", 0) or max(1, nucleos() - 1))
    nums = [int(x) for x in opc("--capitulos", "").split(",") if x.strip()]
    tmp = os.path.abspath(os.path.expanduser(opc("--tmp", os.path.join(base, "tmp"))))
    meta = ler_meta(pacote)
    iso = meta["iso"]
    saida = os.path.abspath(os.path.expanduser(opc("--saida", os.path.join(base, "saida", iso))))
    filme = "--filme" in a
    manter = "--manter-mestre" in a or filme
    if not SECO:
        for p in (base, tmp, saida, os.path.join(base, "logs")):
            os.makedirs(p, exist_ok=True)
        LOG = os.path.join(base, "logs", "%s.log" % iso)
    hf = hyperframes_bin(base)
    caps = [c for c in sorted(meta["capitulos"], key=lambda c: c["n"]) if not nums or c["n"] in nums]
    if nums and len(caps) != len(set(nums)):
        raise SystemExit("o pacote não tem os capítulos %s (tem %s)" % (sorted(set(nums) - {c["n"] for c in caps}),
                                                                       [c["n"] for c in meta["capitulos"]]))
    total_min = sum((c.get("dur_prevista") or 0) for c in caps) / 60
    diz("%s: %d capítulo(s), %.0f min de vídeo; workers=%d; base=%s; tmp=%s (%.0f GB livres); saída=%s"
        % (iso, len(caps), total_min, workers, base, tmp, livre_gb(tmp if os.path.isdir(tmp) else base), saida))
    maior = max((c.get("dur_prevista") or 0) for c in caps) / 60 if caps else 0
    # quadros temporários: no Windows, ~21 GB num capítulo de 14 min (LEIA-ME do país) → ~1,5 GB por minuto
    if not SECO and 0 < livre_gb(tmp) < maior * 1.5 + 5:
        diz("AVISO: pouco espaço em %s (%.0f GB) — o capítulo de %.0f min pode pedir ~%.0f GB de quadros temporários"
            % (tmp, livre_gb(tmp), maior, maior * 1.5 + 5))
    if SECO:
        print("  (dry-run) hyperframes: %s; ffmpeg: %s" % (" ".join(hf), shutil.which("ffmpeg") or "NÃO ACHADO"))
    proj = desempacotar(pacote, os.path.join(base, "trabalho"))
    if isinstance(proj, tuple):
        proj = None
    env = dict(os.environ, TMPDIR=tmp, TEMP=tmp, TMP=tmp, HYPERFRAMES_NO_TELEMETRY="1", DO_NOT_TRACK="1",
               HYPERFRAMES_NO_UPDATE_CHECK="1")
    erros = []
    for cap in caps:
        try:
            capitulo(cap, proj, saida, hf, workers, env, manter)
        except Exception as erro:   # um capítulo com defeito não para os outros
            diz("ERRO em %s: %s" % (cap["pasta"], str(erro)[-1500:]))
            erros.append(cap["pasta"])
    if SECO:
        print("  no fim: indice.json, roteiro.json, capitulos.txt e pronto.json em %s" % saida)
        return
    fechar(meta, proj, saida, filme)
    if erros:
        raise SystemExit("capítulos com erro: %s (rode de novo: retoma do que falta)" % erros)


if __name__ == "__main__":
    main()
