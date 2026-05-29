import csv
import hashlib
import json
import logging
import os
import queue
import random
import threading
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
    funcao_registro=None,
) -> list[dict]:
    navegador = None
    try:
        if not modo_simulacao:
            navegador = criar_navegador()

        resultados: list[dict] = []
        for indice, cidade in enumerate(cidades, start=1):
            mensagem = f"Coletando ({indice}/{len(cidades)}): {cidade}"
            logging.info(mensagem)
            if funcao_registro is not None:
                funcao_registro(mensagem)
            previsao = coletar_previsao_por_cidade(
                cidade=cidade,
                fonte=fonte,
                navegador=navegador,
                modo_simulacao=modo_simulacao,
            )

            previsao["alerta_chuva"] = avaliar_alerta_chuva(previsao, limiar_chuva)
            if previsao["alerta_chuva"]:
                mensagem_alerta = (
                    f"ALERTA: probabilidade de chuva alta ({previsao.get('probabilidade_chuva')}%) "
                    f"para {cidade}"
                )
                logging.warning(mensagem_alerta)
                if funcao_registro is not None:
                    funcao_registro(mensagem_alerta)

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
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
    except ImportError as erro:
        raise RuntimeError(
            "Dependência ausente: selenium. Instale com 'pip install selenium' "
            "ou use o parâmetro --simular."
        ) from erro

    opcoes = Options()
    #opcoes.add_argument("--headless=new")
    opcoes.add_argument("--disable-gpu")
    opcoes.add_argument("--no-sandbox")
    opcoes.add_argument("--start-maximized")

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
    time.sleep(2)
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.support import expected_conditions as condicoes_esperadas
    from selenium.webdriver.support.ui import WebDriverWait

    espera = WebDriverWait(navegador, 15)
    campo_busca = espera.until(condicoes_esperadas.presence_of_element_located((By.ID, "search")))
    try:
        campo_busca.clear()
    except Exception:
        pass
    campo_busca.send_keys(cidade)
    time.sleep(2)
    campo_busca.send_keys(Keys.ARROW_DOWN)
    time.sleep(2)
    campo_busca.send_keys(Keys.ENTER)
    time.sleep(2)

    temperatura_minima = espera.until(condicoes_esperadas.presence_of_element_located((By.CSS_SELECTOR, "#previsao > div:nth-child(1) > div:nth-child(2) > div:nth-child(2) > div:nth-child(3) > b")))
    temperatura_minima_texto = temperatura_minima.text

    temperatura_maxima = espera.until(condicoes_esperadas.presence_of_element_located((By.CSS_SELECTOR, "#previsao > div:nth-child(1) > div:nth-child(2) > div:nth-child(3) > div:nth-child(3) > b")))
    temperatura_maxima_texto = temperatura_maxima.text

    return {
        "cidade": cidade,
        "fonte": "inmet",
        "coletado_em_utc": agora_iso(),
        "temperatura_minima": temperatura_minima_texto,
        "temperatura_maxima": temperatura_maxima_texto,
        "probabilidade_chuva": None,
        "observacao": "raspagem_finalizada",
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


def listar_arquivos_cidades(diretorio_base: str) -> list[str]:
    extensoes = {".txt", ".csv"}
    arquivos: list[str] = []
    diretorio_base_absoluto = os.path.abspath(diretorio_base or ".")

    for raiz, diretorios, nomes in os.walk(diretorio_base_absoluto):
        relativo = os.path.relpath(raiz, diretorio_base_absoluto)
        profundidade = 0 if relativo == "." else relativo.count(os.sep) + 1

        if profundidade > 2:
            diretorios[:] = []
            continue

        nome_raiz = os.path.basename(raiz)
        if nome_raiz in {"venv", ".venv", ".git", "__pycache__", ".github"}:
            diretorios[:] = []
            continue

        for nome in nomes:
            _, extensao = os.path.splitext(nome)
            if extensao.lower() not in extensoes:
                continue
            if nome.casefold() == "requirements.txt":
                continue
            arquivos.append(os.path.join(raiz, nome))

    return sorted(arquivos, key=lambda x: x.casefold())


def exibir_menu_texto() -> dict:
    print("=" * 50)
    print("   Coleta de Dados Climáticos para Logística")
    print("=" * 50)

    while True:
        print("\n1. Selecione o arquivo de cidades (.txt ou .csv):")
        arquivos_disponiveis = listar_arquivos_cidades(os.getcwd())
        if not arquivos_disponiveis:
            print("Erro: Nenhum arquivo .txt ou .csv encontrado no diretório do projeto.")
            continue

        for indice, caminho in enumerate(arquivos_disponiveis, start=1):
            caminho_relativo = os.path.relpath(caminho, os.getcwd())
            print(f"   [{indice}] {caminho_relativo}")

        escolha = input("Digite o número do arquivo desejado: ").strip()
        try:
            indice_escolhido = int(escolha)
        except ValueError:
            print("Erro: Digite um número válido.")
            continue

        if indice_escolhido < 1 or indice_escolhido > len(arquivos_disponiveis):
            print("Erro: Opção inválida. Escolha um número da lista.")
            continue

        arquivo_cidades = arquivos_disponiveis[indice_escolhido - 1]
        break

    while True:
        print("\n2. Escolha a fonte de dados:")
        print("   [1] INMET")
        print("   [2] ClimaTempo")
        opcao_fonte = input("Digite a opção (1 ou 2): ").strip()
        if opcao_fonte == "1":
            fonte = "inmet"
            break
        elif opcao_fonte == "2":
            fonte = "climatempo"
            break
        print("Erro: Opção inválida. Escolha 1 ou 2.")

    while True:
        print("\n3. Escolha o formato de saída dos resultados:")
        print("   [1] JSON")
        print("   [2] CSV")
        opcao_formato = input("Digite a opção (1 ou 2): ").strip()
        if opcao_formato == "1":
            formato_saida = "json"
            break
        elif opcao_formato == "2":
            formato_saida = "csv"
            break
        print("Erro: Opção inválida. Escolha 1 ou 2.")

    while True:
        opcao_simular = input("\n4. Deseja executar em modo de simulação? (S/N): ").strip().upper()
        if opcao_simular in ("S", "N"):
            simular = (opcao_simular == "S")
            break
        print("Erro: Digite apenas S ou N.")

    return {
        "arquivo_cidades": arquivo_cidades,
        "fonte": fonte,
        "formato_saida": formato_saida,
        "simular": simular
    }


def executar_interface_grafica(ctk) -> int:
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")

    fila_mensagens: queue.Queue[str] = queue.Queue()
    estado_execucao = {"codigo": 0}

    raiz = ctk.CTk()
    raiz.title("Coleta de Dados Climáticos")
    raiz.geometry("900x620")
    raiz.minsize(820, 560)

    quadro = ctk.CTkFrame(raiz)
    quadro.pack(fill="both", expand=True, padx=16, pady=16)

    titulo = ctk.CTkLabel(
        quadro,
        text="Coleta de Dados Climáticos para Logística",
        font=ctk.CTkFont(size=20, weight="bold"),
    )
    titulo.pack(anchor="w", padx=16, pady=(16, 8))

    quadro_form = ctk.CTkFrame(quadro)
    quadro_form.pack(fill="x", padx=16, pady=(0, 12))

    rotulo_arquivo = ctk.CTkLabel(quadro_form, text="Arquivo de cidades")
    rotulo_arquivo.grid(row=0, column=0, sticky="w", padx=12, pady=(12, 6))

    mapa_arquivos: dict[str, str] = {}
    selecao_arquivo = ctk.StringVar(value="")

    def carregar_arquivos():
        nonlocal mapa_arquivos
        arquivos = listar_arquivos_cidades(os.getcwd())
        mapa_arquivos = {
            os.path.relpath(caminho, os.getcwd()): caminho for caminho in arquivos
        }
        opcoes = list(mapa_arquivos.keys()) or ["(nenhum arquivo encontrado)"]
        menu_arquivo.configure(values=opcoes)
        if opcoes and selecao_arquivo.get() not in opcoes:
            selecao_arquivo.set(opcoes[0])

    menu_arquivo = ctk.CTkOptionMenu(quadro_form, variable=selecao_arquivo, values=["carregando..."])
    menu_arquivo.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 12))

    botao_atualizar = ctk.CTkButton(quadro_form, text="Atualizar lista", command=carregar_arquivos, width=140)
    botao_atualizar.grid(row=1, column=1, sticky="e", padx=(0, 12), pady=(0, 12))

    quadro_form.grid_columnconfigure(0, weight=1)

    rotulo_fonte = ctk.CTkLabel(quadro_form, text="Fonte")
    rotulo_fonte.grid(row=2, column=0, sticky="w", padx=12, pady=(0, 6))

    selecao_fonte = ctk.StringVar(value="inmet")
    menu_fonte = ctk.CTkSegmentedButton(
        quadro_form,
        values=["inmet", "climatempo"],
        variable=selecao_fonte,
    )
    menu_fonte.grid(row=3, column=0, sticky="w", padx=12, pady=(0, 12))

    rotulo_formato = ctk.CTkLabel(quadro_form, text="Formato de saída")
    rotulo_formato.grid(row=4, column=0, sticky="w", padx=12, pady=(0, 6))

    selecao_formato = ctk.StringVar(value="json")
    menu_formato = ctk.CTkSegmentedButton(
        quadro_form,
        values=["json", "csv"],
        variable=selecao_formato,
    )
    menu_formato.grid(row=5, column=0, sticky="w", padx=12, pady=(0, 12))

    selecao_simular = ctk.BooleanVar(value=True)
    botao_simular = ctk.CTkSwitch(
        quadro_form,
        text="Executar em modo simulação (sem Selenium)",
        variable=selecao_simular,
        onvalue=True,
        offvalue=False,
    )
    botao_simular.grid(row=6, column=0, sticky="w", padx=12, pady=(0, 12))

    rotulo_log = ctk.CTkLabel(quadro, text="Log")
    rotulo_log.pack(anchor="w", padx=16, pady=(0, 6))

    caixa_log = ctk.CTkTextbox(quadro, height=260)
    caixa_log.pack(fill="both", expand=True, padx=16, pady=(0, 12))

    quadro_botoes = ctk.CTkFrame(quadro, fg_color="transparent")
    quadro_botoes.pack(fill="x", padx=16, pady=(0, 16))

    botao_iniciar = ctk.CTkButton(quadro_botoes, text="Iniciar", width=140)
    botao_iniciar.pack(side="right")

    botao_fechar = ctk.CTkButton(quadro_botoes, text="Fechar", width=140, command=raiz.destroy)
    botao_fechar.pack(side="right", padx=(0, 10))

    def adicionar_log(texto: str) -> None:
        fila_mensagens.put(texto)

    def descarregar_log():
        alterou = False
        while True:
            try:
                item = fila_mensagens.get_nowait()
            except queue.Empty:
                break
            caixa_log.insert("end", item + "\n")
            caixa_log.see("end")
            alterou = True

        if alterou:
            caixa_log.update_idletasks()
        raiz.after(150, descarregar_log)

    def definir_estado_controles(habilitado: bool) -> None:
        estado = "normal" if habilitado else "disabled"
        menu_arquivo.configure(state=estado)
        botao_atualizar.configure(state=estado)
        menu_fonte.configure(state=estado)
        menu_formato.configure(state=estado)
        botao_simular.configure(state=estado)
        botao_iniciar.configure(state=estado)

    def executar_trabalho(arquivo_escolhido: str, fonte: str, formato_saida: str, simular: bool) -> None:
        codigo, caminho_saida, erro = executar_fluxo(
            arquivo_cidades=arquivo_escolhido,
            fonte=fonte,
            formato_saida=formato_saida,
            simular=simular,
            funcao_registro=adicionar_log,
        )
        estado_execucao["codigo"] = int(codigo)
        if erro:
            adicionar_log(f"Erro: {erro}")
        elif caminho_saida:
            adicionar_log(f"Concluído. Resultado salvo em: {caminho_saida}")
        else:
            adicionar_log(f"Finalizado com código: {codigo}")

        raiz.after(0, lambda: definir_estado_controles(True))

    def iniciar():
        chave_arquivo = (selecao_arquivo.get() or "").strip()
        caminho_arquivo = mapa_arquivos.get(chave_arquivo, "")
        if not caminho_arquivo or not os.path.exists(caminho_arquivo):
            adicionar_log("Erro: selecione um arquivo de cidades válido.")
            return

        fonte = (selecao_fonte.get() or "").strip()
        formato_saida = (selecao_formato.get() or "").strip()
        simular = bool(selecao_simular.get())

        definir_estado_controles(False)
        adicionar_log("Iniciando...")

        thread = threading.Thread(
            target=executar_trabalho,
            kwargs={
                "arquivo_escolhido": caminho_arquivo,
                "fonte": fonte,
                "formato_saida": formato_saida,
                "simular": simular,
            },
            daemon=True,
        )
        thread.start()

    botao_iniciar.configure(command=iniciar)

    carregar_arquivos()
    descarregar_log()

    raiz.mainloop()
    return int(estado_execucao["codigo"])


def executar_fluxo(
    arquivo_cidades: str,
    fonte: str,
    formato_saida: str,
    simular: bool,
    funcao_registro=None,
) -> tuple[int, str, str]:
    try:
        configurar_registro(1)
        cidades = carregar_cidades(arquivo_cidades)
        if not cidades:
            return 2, "", "Nenhuma cidade encontrada no arquivo."

        resultados = coletar_previsoes(
            cidades=cidades,
            fonte=fonte,
            limiar_chuva=80,
            modo_simulacao=bool(simular),
            espera_entre_cidades_segundos=0.5,
            funcao_registro=funcao_registro,
        )

        caminho_saida = f"saidas/previsoes.{formato_saida}"
        salvar_saida(resultados, caminho_saida, formato_saida)
        return 0, caminho_saida, ""
    except Exception as erro:
        return 2, "", str(erro)


def executar() -> int:
    try:
        import customtkinter as ctk
    except ImportError:
        configuracoes = exibir_menu_texto()
        codigo, caminho_saida, erro = executar_fluxo(
            arquivo_cidades=configuracoes["arquivo_cidades"],
            fonte=configuracoes["fonte"],
            formato_saida=configuracoes["formato_saida"],
            simular=configuracoes["simular"],
            funcao_registro=print,
        )
        if erro:
            print(f"Erro: {erro}")
        elif caminho_saida:
            print(f"Concluído. Resultado salvo em: {caminho_saida}")
        return int(codigo)

    return executar_interface_grafica(ctk)


if __name__ == "__main__":
    raise SystemExit(executar())
