import re
from playwright.sync_api import Playwright, sync_playwright, expect


def run(playwright: Playwright) -> None:
    browser = playwright.chromium.launch(headless=False)
    context = browser.new_context(ignore_https_errors=True)
    page = context.new_page()
    page.goto("https://10.252.17.132/aghu/pages/casca/casca.xhtml")
    page.get_by_role("textbox", name="Nome de usuário").click()
    page.get_by_role("textbox", name="Nome de usuário").fill("16390588852")
    page.get_by_role("textbox", name="Senha").click()
    page.get_by_role("textbox", name="Senha").fill("Napoli2026)")
    page.get_by_role("button", name="Entrar").click()
    page.goto("https://10.252.17.132/aghu/pages/casca/casca.xhtml")
    page.get_by_role("button", name="Fechar").click()
    page.locator("[id=\"_icon_img_20352\"]").click()
    # identificar o input element para escolher a data
    # <input id="dataAlta:dataAlta:inputId_input" name="dataAlta:dataAlta:inputId_input" type="text" value="11/05/2026" class="ui-inputfield ui-widget ui-state-default ui-corner-all ui-state-filled hasDatepicker" autocomplete="off" size="15" tabindex="" aria-required="true" inputmode="text">
    page.locator("iframe[name=\"i_frame_altas_do_dia\"]").content_frame.locator("[id=\"dataAlta:dataAlta:inputId_input\"]").click()
    #clicar em "Visualizar Impressão"
    page.locator("iframe[name=\"i_frame_altas_do_dia\"]").content_frame.get_by_role("button", name="Visualizar Impressão").click()
    # baixar o pdf clicando no ícone de impressão do visualizador do pdf, no elemento abaixo
    # <cr-icon-button id="print" iron-icon="pdf:print" title="Imprimir" aria-label="Imprimir" role="button" tabindex="0" aria-disabled="false"><template shadowrootmode="open"><!---->
    # <div id="icon">
    #   <div id="maskedImage"></div>
    # <cr-icon><template shadowrootmode="open"><svg id="baseSvg" xmlns="http://www.w3.org/2000/svg" preserveAspectRatio="xMidYMid meet" focusable="false" viewBox="0 -960 960 960" class="cr-iconset-svg-icon_" role="none" style="display: block; height: 100%; width: 100%; pointer-events: none;">
    #  <g viewBox="0 -960 960 960"><path d="M648-624v-120H312v120h-72v-192h480v192h-72Zm-480 72h625-625Zm539.79 96q15.21 0 25.71-10.29t10.5-25.5q0-15.21-10.29-25.71t-25.5-10.5q-15.21 0-25.71 10.29t-10.5 25.5q0 15.21 10.29 25.71t25.5 10.5ZM648-216v-144H312v144h336Zm72 72H240v-144H96v-240q0-40 28-68t68-28h576q40 0 68 28t28 68v240H720v144Zm73-216v-153.67Q793-530 781-541t-28-11H206q-16.15 0-27.07 11.04Q168-529.92 168-513.6V-360h72v-72h480v72h73Z"></path></g></svg><!----></template></cr-icon></div><cr-ripple id="ink"><template shadowrootmode="open"><!----></template></cr-ripple></template>
    #     </cr-icon-button>


    # ---------------------
    context.close()
    browser.close()


with sync_playwright() as playwright:
    run(playwright)
