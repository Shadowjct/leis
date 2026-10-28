"""Ingestao complementar de leis estaduais promulgadas pela ALBA via EGBA oficial.

Somente publicacoes claramente classificadas no sumario como Lei Ordinaria,
com artigos verificaveis; materiais com anexos/imagens/tabelas ficam retidos.
Nenhum checkout/clone do corpus. Consultas de existencia feitas por API GitHub
no diretorio anual, para detectar colisoes mesmo com nomes de arquivo diferentes.
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
from html.parser import HTMLParser
import json
import os
import re
import time
import unicodedata
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

ROOT = "https://egbanet.egba.ba.gov.br/alba"
REPO = "Shadowjct/leis"
YEAR_DIR = "estaduais/BA/leis-ordinarias/{ano}"
MONTHS = {
    "janeiro": 1, "fevereiro": 2, "marco": 3, "abril": 4,
    "maio": 5, "junho": 6, "julho": 7, "agosto": 8,
    "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12,
}


def fold(text):
    return "".join(x for x in unicodedata.normalize("NFD", text)
                   if unicodedata.category(x) != "Mn").casefold()


def official(url):
    if not url.startswith(ROOT + "/"):
        raise ValueError("Fonte fora da EGBA/ALBA")
    req = Request(url, headers={"User-Agent": "leis-bahia-alba/1.0", "Accept-Encoding": "identity"})
    with urlopen(req, timeout=35) as response:
        data = response.read(2_000_001)
        if response.status != 200 or len(data) > 2_000_000:
            raise RuntimeError("Fonte ausente ou excessivamente grande: " + url)
    return data


class Summary(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.current = None
        self.pieces = []
        self.items = []

    def handle_starttag(self, tag, attrs):
        props = dict(attrs)
        if tag == "a" and "linkMateria" in props.get("class", "").split():
            code = props.get("identificador", "")
            if code.isdecimal():
                self.current = code
                self.pieces = []

    def handle_data(self, data):
        if self.current:
            self.pieces.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self.current:
            self.items.append((self.current, " ".join(self.pieces).strip()))
            self.current = None
            self.pieces = []


class Paragraphs(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_body = False
        self.active = False
        self.pieces = []
        self.lines = []
        self.unsafe = set()

    def handle_starttag(self, tag, attrs):
        if tag == "body":
            self.in_body = True
        if self.in_body and tag in ("table", "img", "svg", "canvas", "object", "iframe"):
            self.unsafe.add(tag)
        if self.in_body and tag in ("p", "li", "h1", "h2", "h3"):
            if self.active:
                raise ValueError("Elementos de texto aninhados")
            self.active = True
            self.pieces = []
        if self.active and tag == "br":
            self.pieces.append(" ")

    def handle_data(self, data):
        if self.active:
            self.pieces.append(data)

    def handle_endtag(self, tag):
        if self.active and tag in ("p", "li", "h1", "h2", "h3"):
            text = re.sub(r"\s+", " ", "".join(self.pieces)).strip()
            if text:
                self.lines.append(text)
            self.pieces = []
            self.active = False
        if tag == "body":
            self.in_body = False


def law_from_label(label, edition_year):
    label = re.sub(r"\s+", " ", label).strip()
    match = re.search(r"\bLEI\s+(?:N[.º°o]*\s*)?(\d{1,2}\.\d{3}|\d{4,5})\s*[_/-]\s*(\d{4})\b",
                      label, re.I)
    if not match or int(match.group(2)) != edition_year:
        return None
    return int(match.group(1).replace(".", ""))


def text_number(header):
    match = re.match(r"^LEI\s+N[.º°o]*\s*([\d.]+)\s*[,/-]", header, re.I)
    return int(match.group(1).replace(".", "")) if match else None


def extract_date(header):
    match = re.search(r"\bDE\s+(\d{1,2})\s+DE\s+([A-Za-zÀ-ÿ]+)\s+DE\s+(\d{4})\b", header, re.I)
    if not match:
        raise ValueError("Data da epigrafe ausente")
    month = MONTHS.get(fold(match.group(2)))
    if not month:
        raise ValueError("Mes desconhecido na epigrafe")
    return dt.date(int(match.group(3)), month, int(match.group(1)))


def norm_number(filename):
    match = re.search(r"(?:^|[-_])(\d{4,5})(?=[-_])", filename)
    return int(match.group(1)) if match else None


def read_edition(date):
    url = ROOT + "/apifront/portal/edicoes/edicoes_from_data/" + date.isoformat() + ".json"
    payload = json.loads(official(url).decode("utf-8"))
    if payload.get("erro"):
        raise RuntimeError("API EGBA: " + str(payload.get("msg")))
    editions = []
    for item in payload.get("itens", []):
        if "Assembleia Legislativa" not in item.get("tipo_edicao_nome", ""):
            continue
        if str(item.get("data", "")).replace("\\/", "/") != date.strftime("%d/%m/%Y"):
            raise ValueError("Data oficial de edicao divergente")
        edition_id = int(item["id"])
        edition_number = int(item["numero"])
        editions.append((edition_id, edition_number))
    return editions


def laws_on(date, edition_id):
    summary_url = ROOT + "/portal/visualizacoes/view_html_diario/" + str(edition_id)
    summary = Summary()
    summary.feed(official(summary_url).decode("utf-8"))
    found = {}
    for ident, label in summary.items:
        number = law_from_label(label, date.year)
        if number:
            if number in found and found[number] != ident:
                raise ValueError("Numero duplicado na mesma edicao " + str(number))
            found[number] = ident
    return found


def extract_law(raw, number, edition_date):
    html = raw.decode("utf-8", "strict")
    p = Paragraphs()
    p.feed(html)
    if p.unsafe:
        raise ValueError("Layout nao linear: " + ",".join(sorted(p.unsafe)))
    lines = p.lines
    if not 6 <= len(lines) <= 2000:
        raise ValueError("Quantidade incompativel de paragrafos")
    if text_number(lines[0]) != number:
        raise ValueError("Epigrafe nao confere com sumario")
    date = extract_date(lines[0])
    if date > edition_date or date.year != edition_date.year:
        raise ValueError("Data da lei posterior a edicao ou fora do ano")
    if not any("ASSEMBLEIA LEGISLATIVA DO ESTADO DA BAHIA" in line.upper() for line in lines[:5]):
        raise ValueError("Promulgacao pela ALBA nao comprovada")
    if not any("presidente" in fold(line) for line in lines[-5:]):
        raise ValueError("Assinatura da Presidencia ausente")
    articles = [int(m.group(1)) for line in lines
                if (m := re.match(r"^Art\.\s*(\d{1,3})\b", line, re.I))]
    if not articles or articles != list(range(1, len(articles) + 1)):
        raise ValueError("Artigos nao consecutivos ou artigo 1 ausente")
    if len("\n".join(lines)) < 500:
        raise ValueError("Texto normativo demasiado curto")
    body = "\n\n".join(lines)
    return date, lines[1], body, len(articles)


def gh(method, path, token="", payload=None):
    url = "https://api.github.com/repos/" + REPO + "/contents/" + quote(path, safe="/")
    if method == "GET":
        url += "?ref=main"
    headers = {"Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "leis-bahia-alba/1.0"}
    if token:
        headers["Authorization"] = "Bearer " + token
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = Request(url, headers=headers, data=data, method=method)
    try:
        with urlopen(req, timeout=40) as response:
            return response.status, json.loads(response.read())
    except HTTPError as exc:
        if method == "GET" and exc.code == 404:
            return 404, None
        raise RuntimeError(f"GitHub API {method}: HTTP {exc.code}, {exc.read(300)!r}") from exc


def existing_numbers(year, token):
    status, listing = gh("GET", YEAR_DIR.format(ano=year), token)
    if status == 404:
        return set()
    if status != 200 or not isinstance(listing, list) or len(listing) >= 1000:
        raise RuntimeError("Diretorio anual indisponivel, malformado ou truncado")
    names = [x["name"] for x in listing if x.get("type") == "file"]
    numbers = [norm_number(name) for name in names]
    # Never publish based on unrecognized legacy filenames: manual review required.
    if any(n is None for n in numbers):
        raise RuntimeError("Nome de arquivo anual fora do padrao, revisar anti-duplicacao")
    return set(numbers)


def markdown(number, date, issue_date, issue_number, edition_id, source_id, raw, ementa, text, count):
    source = ROOT + "/apifront/portal/edicoes/publicacoes_ver_conteudo/" + source_id
    meta = {
        "titulo": f"Lei Ordinaria nº {number//1000}.{number%1000:03d}, de {date.day:02d}/{date.month:02d}/{date.year}",
        "uf": "BA",
        "tipo": "Lei Ordinaria",
        "numero": str(number),
        "data": date.isoformat(),
        "ementa": ementa,
        "orgao": "Assembleia Legislativa do Estado da Bahia",
        "publicacao": f"Diario Oficial do Legislativo nº {issue_number}, de {issue_date.strftime('%d/%m/%Y')}",
        "versao_texto": "publicacao original ALBA/EGBA, nao compilada e sem certificacao de vigencia atual",
        "fonte": ROOT + "/ver-html/" + str(edition_id) + "/#e:" + str(edition_id) + "/m:" + source_id,
        "fonte_texto": source,
        "sha256_fonte": hashlib.sha256(raw).hexdigest(),
        "sha256_texto": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "artigos_identificados": str(count),
    }
    hdr = "\n".join(f"{k}: {json.dumps(v, ensure_ascii=False)}" for k, v in meta.items())
    return "---\n" + hdr + "\n---\n\n# " + meta["titulo"] + "\n\n" + text + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-inicial", required=True)
    parser.add_argument("--dias", type=int, default=1)
    parser.add_argument("--max-novas", type=int, default=15)
    parser.add_argument("--simular", action="store_true")
    args = parser.parse_args()
    start = dt.date.fromisoformat(args.data_inicial)
    if not (1 <= args.dias <= 7 and 1 <= args.max_novas <= 40
            and 1900 <= start.year <= 2026
            and start + dt.timedelta(days=args.dias - 1) <= dt.date(2026, 10, 28)):
        raise SystemExit("Datas/limites fora do intervalo permitido")
    repo = os.environ.get("GITHUB_REPOSITORY")
    ref = os.environ.get("GITHUB_REF")
    if repo not in (None, REPO) or ref not in (None, "refs/heads/main"):
        raise SystemExit("Repositorio/ref nao autorizado")
    token = os.environ.get("GH_TOKEN", "")
    if not args.simular and (repo != REPO or ref != "refs/heads/main" or not token):
        raise SystemExit("Gravacao requer runner oficial com GITHUB_TOKEN")
    seen = {}
    counts = {"edicoes": 0, "leis_identificadas": 0, "ja_existentes": 0,
              "novas": 0, "retidas": 0}
    for offset in range(args.dias):
        day = start + dt.timedelta(days=offset)
        year_set = seen.setdefault(day.year, existing_numbers(day.year, token))
        for ed_id, ed_no in read_edition(day):
            counts["edicoes"] += 1
            numbers = laws_on(day, ed_id)
            counts["leis_identificadas"] += len(numbers)
            for number, source_id in sorted(numbers.items()):
                if number in year_set:
                    counts["ja_existentes"] += 1
                    continue
                url = ROOT + "/apifront/portal/edicoes/publicacoes_ver_conteudo/" + source_id
                raw = official(url)
                try:
                    law_date, ementa, body, count = extract_law(raw, number, day)
                except (ValueError, UnicodeError) as ex:
                    counts["retidas"] += 1
                    print("RETIDA", number, source_id, str(ex), flush=True)
                    continue
                path = YEAR_DIR.format(ano=law_date.year) + f"/lei-ordinaria-{number}-{law_date.year}-alba-{source_id}.md"
                if counts["novas"] >= args.max_novas:
                    print("LIMITE ALCANCADO", path, flush=True)
                    continue
                text = markdown(number, law_date, day, ed_no, ed_id, source_id,
                                raw, ementa, body, count)
                if args.simular:
                    print("SIMULACAO NOVA", number, path, "artigos", count, flush=True)
                else:
                    # Recheck directory and exact path immediately before an irreversible write.
                    if number in existing_numbers(law_date.year, token):
                        print("COLISAO: numero ja publicado", number, flush=True)
                        counts["ja_existentes"] += 1
                        year_set.add(number)
                        continue
                    status, _ = gh("GET", path, token)
                    if status != 404:
                        raise RuntimeError(f"Destino deixou de estar ausente: {path}")
                    payload = {"message": f"feat(BA): adicionar Lei estadual {number}/{law_date.year} ALBA",
                               "content": base64.b64encode(text.encode("utf-8")).decode("ascii"),
                               "branch": "main"}
                    status, saved = gh("PUT", path, token, payload)
                    if status != 201:
                        raise RuntimeError("Criacao nao retornou HTTP 201")
                    status, check = gh("GET", path, token)
                    if status != 200 or check.get("sha") != saved["content"]["sha"]:
                        raise RuntimeError("Verificacao de persistencia falhou")
                    print("PUBLICADA", number, path, saved["commit"]["sha"], flush=True)
                counts["novas"] += 1
                year_set.add(number)
            time.sleep(0.3)
    print("RESUMO", json.dumps({**counts, "simulacao": args.simular}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
