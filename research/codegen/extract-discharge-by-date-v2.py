import re
from playwright.sync_api import Playwright, sync_playwright, expect


def run(playwright: Playwright) -> None:
    browser = playwright.chromium.launch(headless=False)
    context = browser.new_context(ignore_https_errors=True)
    page = context.new_page()
    page.goto("https://10.252.17.132/aghu/pages/casca/casca.xhtml")
    page.get_by_role("textbox", name="Nome de usuário").click()
    page.get_by_role("textbox", name="Nome de usuário").fill("16390588852")
    page.get_by_role("textbox", name="Nome de usuário").press("Tab")
    page.get_by_role("textbox", name="Senha").click()
    page.get_by_role("textbox", name="Senha").fill("Napoli2026)")
    page.get_by_role("button", name="Entrar").click()
    page.get_by_role("button", name="Fechar").click()
    page.locator("[id=\"_icon_img_20341\"]").click()
    # aguardar o iframe carregar

    # identificar o input element para dataInicial
    # <input id="dataInicial:dataInicial:inputId_input" name="dataInicial:dataInicial:inputId_input" type="text" value="15/05/2026" class="ui-inputfield ui-widget ui-state-default ui-corner-all ui-state-filled hasDatepicker" autocomplete="off" size="15" tabindex="" aria-required="true" inputmode="text">
    page.locator("iframe[name=\"i_frame_pesquisar_pacientes_com_alta\"]").content_frame.locator("[id=\"dataInicial:dataInicial:inputId_input\"]").click()
    # preencher a data

    #identificar o input element para a dataFinal
    # <input id="dataFinal:dataFinal:inputId_input" name="dataFinal:dataFinal:inputId_input" type="text" value="15/05/2026" class="ui-inputfield ui-widget ui-state-default ui-corner-all ui-state-filled hasDatepicker" autocomplete="off" size="15" tabindex="" aria-required="true" inputmode="text">
    page.locator("iframe[name=\"i_frame_pesquisar_pacientes_com_alta\"]").content_frame.locator("[id=\"dataFinal:dataFinal:inputId_input\"]").click()
    #preencher a data

    # aguardar o resultado
    page.locator("iframe[name=\"i_frame_pesquisar_pacientes_com_alta\"]").content_frame.get_by_role("button", name="Exportar para Arquivo").click()
    with page.expect_download() as download_info:
        page.locator("iframe[name=\"i_frame_pesquisar_pacientes_com_alta\"]").content_frame.locator("a").filter(has_text="XLS (Tudo)").click()
    download = download_info.value

    # ---------------------
    context.close()
    browser.close()


with sync_playwright() as playwright:
    run(playwright)
