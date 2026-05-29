import argparse
import csv
import hashlib
import json
import logging
import os
import random
import sys
import time
from datetime import datetime, timezone


def configurar_registro(nivel_verbosidade: int) -> None:
    nivel = logging.INFO
    if nivel_verbosidade >= 2:
        nivel = logging.DEBUG
    elif nivel_verbosidade == 0:
        nivel = logging.WARNING

    logging.basicConfig(
        level=nivel,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def carregar_cidades(caminho_arquivo_cidades: str) -> list[str]:
    if not caminho_arquivo_cidades:
        raise ValueError("O caminho do arquivo de cidades é obrigatório.")

    if not os.path.exists(caminho_arquivo_cidades):
        raise FileNotFoundError(f"Arquivo não encontrado: {caminho_arquivo_cidades}")

    extensao = os.path.splitext(caminho_arquivo_cidades)[1].lower().strip(".")

    if extensao == "txt":
        return carregar_cidades_de_txt(caminho_arquivo_cidades)
    if extensao == "csv":
        return carregar_cidades_de_csv(caminho_arquivo_cidades)

    raise ValueError("Formato não suportado. Use .txt ou .csv.")


def carregar_cidades_de_txt(caminho_arquivo_cidades: str) -> list[str]:
    cidades: list[str] = []
    with open(caminho_arquivo_cidades, "r", encoding="utf-8") as arquivo:
        for linha in arquivo:
            cidade = normalizar_texto(linha)
            if cidade:
                cidades.append(cidade)
    return remover_duplicadas_preservando_ordem(cidades)


def carregar_cidades_de_csv(caminho_arquivo_cidades: str) -> list[str]:
    cidades: list[str] = []
    with open(caminho_arquivo_cidades, "r", encoding="utf-8-sig", newline="") as arquivo:
        leitor = csv.reader(arquivo)
        linhas = list(leitor)

    if not linhas:
        return []

    cabecalho = [normalizar_texto(x) for x in linhas[0]]
    indice_cidade = None

    for i, coluna in enumerate(cabecalho):
        if coluna in {"cidade", "municipio", "município"}:
            indice_cidade = i
            break

    inicio = 1 if indice_cidade is not None else 0
    if indice_cidade is None:
        indice_cidade = 0

    for linha in linhas[inicio:]:
        if not linha:
            continue
        if indice_cidade >= len(linha):
            continue
        cidade = normalizar_texto(linha[indice_cidade])
        if cidade:
            cidades.append(cidade)

    return remover_duplicadas_preservando_ordem(cidades)


def remover_duplicadas_preservando_ordem(itens: list[str]) -> list[str]:
    vistos: set[str] = set()
    saida: list[str] = []
    for item in itens:
        chave = item.casefold()
        if chave in vistos:
            continue
        vistos.add(chave)
        saida.append(item)
    return saida


def normalizar_texto(valor: str) -> str:
    return (valor or "").strip()


def agora_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def coletar_previsoes(
    cidades: list[str],
    fonte: str,
    limiar_chuva: int,
    modo_simulacao: bool,
    espera_entre_cidades_segundos: float,
) -> list[dict]:
    navegador = None
    try:
        if not modo_simulacao:
            navegador = criar_navegador()

        resultados: list[dict] = []
        for indice, cidade in enumerate(cidades, start=1):
            logging.info("Coletando (%s/%s): %s", indice, len(cidades), cidade)
            previsao = coletar_previsao_por_cidade(
                cidade=cidade,
                fonte=fonte,
                navegador=navegador,
                modo_simulacao=modo_simulacao,
            )

            previsao["alerta_chuva"] = avaliar_alerta_chuva(previsao, limiar_chuva)
            if previsao["alerta_chuva"]:
                logging.warning(
                    "ALERTA: probabilidade de chuva alta (%s%%) para %s",
                    previsao.get("probabilidade_chuva"),
                    cidade,
                )

            resultados.append(previsao)

            if espera_entre_cidades_segundos > 0 and indice < len(cidades):
                time.sleep(espera_entre_cidades_segundos)

        return resultados
    finally:
        encerrar_navegador(navegador)


def coletar_previsao_por_cidade(
    cidade: str,
    fonte: str,
    navegador,
    modo_simulacao: bool,
) -> dict:
    fonte_normalizada = normalizar_texto(fonte).casefold()
    if modo_simulacao:
        return simular_previsao(cidade, fonte_normalizada)

    if fonte_normalizada in {"inmet"}:
        return coletar_previsao_inmet(cidade=cidade, navegador=navegador)
    if fonte_normalizada in {"climatempo", "clima_tempo", "clima-tempo"}:
        return coletar_previsao_climatempo(cidade=cidade, navegador=navegador)

    raise ValueError("Fonte inválida. Use 'inmet' ou 'climatempo'.")


def avaliar_alerta_chuva(previsao: dict, limiar_chuva: int) -> bool:
    probabilidade = previsao.get("probabilidade_chuva")
    if probabilidade is None:
        return False
    try:
        return int(probabilidade) >= int(limiar_chuva)
    except (TypeError, ValueError):
        return False


def simular_previsao(cidade: str, fonte: str) -> dict:
    semente = hashlib.sha256((cidade + "|" + fonte).encode("utf-8")).hexdigest()
    gerador = random.Random(int(semente[:8], 16))

    temperatura_minima = gerador.randint(10, 26)
    temperatura_maxima = temperatura_minima + gerador.randint(3, 12)
    probabilidade_chuva = gerador.randint(0, 100)

    return {
        "cidade": cidade,
        "fonte": fonte,
        "coletado_em_utc": agora_iso(),
        "temperatura_minima": temperatura_minima,
        "temperatura_maxima": temperatura_maxima,
        "probabilidade_chuva": probabilidade_chuva,
        "observacao": "simulacao",
    }


def criar_navegador():
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
    except ImportError as erro:
        raise RuntimeError(
            "Dependência ausente: selenium. Instale com 'pip install selenium' "
            "ou use o parâmetro --simular."
        ) from erro

    opcoes = Options()
    opcoes.add_argument("--headless=new")
    opcoes.add_argument("--disable-gpu")
    opcoes.add_argument("--no-sandbox")
    opcoes.add_argument("--window-size=1366,768")

    try:
        return webdriver.Chrome(options=opcoes)
    except Exception as erro:
        raise RuntimeError(
            "Falha ao iniciar o Chrome via Selenium. Verifique Chrome/Driver "
            "ou use --simular para validar o fluxo."
        ) from erro


def encerrar_navegador(navegador) -> None:
    try:
        if navegador is not None:
            navegador.quit()
    except Exception:
        return


def coletar_previsao_inmet(cidade: str, navegador) -> dict:
    if navegador is None:
        raise RuntimeError("Navegador não inicializado.")

    url = "https://portal.inmet.gov.br/"
    navegador.get(url)

    return {
        "cidade": cidade,
        "fonte": "inmet",
        "coletado_em_utc": agora_iso(),
        "temperatura_minima": None,
        "temperatura_maxima": None,
        "probabilidade_chuva": None,
        "observacao": "raspagem_pendente",
    }


def coletar_previsao_climatempo(cidade: str, navegador) -> dict:
    if navegador is None:
        raise RuntimeError("Navegador não inicializado.")

    url = "https://www.climatempo.com.br/"
    navegador.get(url)

    return {
        "cidade": cidade,
        "fonte": "climatempo",
        "coletado_em_utc": agora_iso(),
        "temperatura_minima": None,
        "temperatura_maxima": None,
        "probabilidade_chuva": None,
        "observacao": "raspagem_pendente",
    }


def salvar_saida(resultados: list[dict], caminho_saida: str, formato_saida: str) -> None:
    if not caminho_saida:
        return

    formato = normalizar_texto(formato_saida).casefold()
    os.makedirs(os.path.dirname(caminho_saida) or ".", exist_ok=True)

    if formato == "json":
        with open(caminho_saida, "w", encoding="utf-8") as arquivo:
            json.dump(resultados, arquivo, ensure_ascii=False, indent=2)
        return

    if formato == "csv":
        campos = [
            "cidade",
            "fonte",
            "coletado_em_utc",
            "temperatura_minima",
            "temperatura_maxima",
            "probabilidade_chuva",
            "alerta_chuva",
            "observacao",
        ]
        with open(caminho_saida, "w", encoding="utf-8", newline="") as arquivo:
            escritor = csv.DictWriter(arquivo, fieldnames=campos)
            escritor.writeheader()
            for item in resultados:
                escritor.writerow({campo: item.get(campo) for campo in campos})
        return

    raise ValueError("Formato de saída inválido. Use 'json' ou 'csv'.")


def criar_argumentos() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="coleta_dados_climaticos",
        description="Robô de coleta de previsões para logística (INMET/ClimaTempo).",
    )

    parser.add_argument(
        "--arquivo-cidades",
        required=True,
        help="Caminho do arquivo .txt ou .csv contendo uma cidade por linha (ou coluna cidade).",
    )
    parser.add_argument(
        "--fonte",
        default="inmet",
        choices=["inmet", "climatempo"],
        help="Fonte de dados climáticos.",
    )
    parser.add_argument(
        "--limiar-chuva",
        type=int,
        default=80,
        help="Gera alerta quando probabilidade de chuva for maior ou igual ao limiar.",
    )
    parser.add_argument(
        "--saida",
        default="",
        help="Caminho de saída para salvar os resultados (opcional).",
    )
    parser.add_argument(
        "--formato-saida",
        default="json",
        choices=["json", "csv"],
        help="Formato do arquivo de saída.",
    )
    parser.add_argument(
        "--simular",
        action="store_true",
        help="Executa o fluxo em modo de simulação (sem Selenium).",
    )
    parser.add_argument(
        "--espera-entre-cidades",
        type=float,
        default=0.5,
        help="Espera (segundos) entre coletas para reduzir bloqueios em sites.",
    )
    parser.add_argument(
        "-v",
        "--verboso",
        action="count",
        default=1,
        help="Aumenta verbosidade (use -v ou -vv).",
    )

    return parser


def executar(argv: list[str]) -> int:
    parser = criar_argumentos()
    args = parser.parse_args(argv)

    configurar_registro(args.verboso)

    cidades = carregar_cidades(args.arquivo_cidades)
    if not cidades:
        logging.warning("Nenhuma cidade encontrada no arquivo.")
        return 2

    resultados = coletar_previsoes(
        cidades=cidades,
        fonte=args.fonte,
        limiar_chuva=args.limiar_chuva,
        modo_simulacao=bool(args.simular),
        espera_entre_cidades_segundos=float(args.espera_entre_cidades),
    )

    salvar_saida(resultados, args.saida, args.formato_saida)

    for item in resultados:
        cidade = item.get("cidade")
        tmin = item.get("temperatura_minima")
        tmax = item.get("temperatura_maxima")
        prob = item.get("probabilidade_chuva")
        alerta = "SIM" if item.get("alerta_chuva") else "NAO"
        print(f"{cidade} | min={tmin} | max={tmax} | chuva%={prob} | alerta={alerta}")

    return 0


if __name__ == "__main__":
    raise SystemExit(executar(sys.argv[1:]))

