# -*- coding: utf-8 -*-

"""
Created on 01. 03. 2026 at 21:24:29

Author: Richard Redina
Email: 195715@vut.cz
Affiliation:
         International Clinical Research Center, Brno
         Brno University of Technology, Brno
GitHub: RicRedi

(._.)
 <|>
_/|_

Description:

"""
import json
import time
import os
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager # Tohle doporučuji!

def get_latest_file(download_dir):
    """Returns the path of the most recently modified file in the given directory."""
    files = [os.path.join(download_dir, f) for f in os.listdir(download_dir)]
    if not files:
        return None
    # Vrátí soubor s nejnovějším časem změny
    return max(files, key=os.path.getmtime)

# download_folder = r"C:\SIVIN_Mateostations\downloads"

# Načte data ze souboru .env
load_dotenv(os.path.splitext(os.path.abspath(__file__))[0] + ".env")

username = os.getenv("SIVIN_USER")
password = os.getenv("SIVIN_PASSWORD")
download_folder = os.getenv("DOWNLOAD_FOLDER")


# 1. Nastavení (Headless mód - nepouští okno prohlížeče, běží na pozadí)
chrome_options = Options()

# Tady jsou ty klíčové preference
prefs = {
    # 1. Automatické ukládání do složky (to už jsme řešili)
    "download.default_directory": download_folder,
    "download.prompt_for_download": False,
    "download.directory_upgrade": True,

    # 2. TOHLE VYŘEŠÍ TVŮJ PROBLÉM: Povolí vícenásobné stahování bez ptaní
    "profile.default_content_setting_values.automatic_downloads": 1,

    # Bonus: Vypne safe browsing varování u některých typů souborů
    "safebrowsing.enabled": True
}

chrome_options.add_experimental_option("prefs", prefs)
# chrome_options.add_argument("--headless") # Odstraň křížek, až to budeš mít odladěné
service = Service(ChromeDriverManager().install())
# Tady to hlásí Error, ale je to v pohodě... tak nevím
driver = webdriver.Chrome(service=service, options = chrome_options)
wait = WebDriverWait(driver, 15) # Maximální doba čekání na prvek
wait.until(EC.invisibility_of_element_located((By.ID, "UpdateProgress")))

try:
    # 2. Otevření stránky (ReturnUrl tě hodí rovnou na login)
    driver.get("https://lemon.e-service.cz/")

    # 3. Vyplnění jména
    username_field = wait.until(EC.presence_of_element_located((By.ID, "username")))
    username_field.send_keys(username)

    # 4. Vyplnění hesla
    password_field = driver.find_element(By.ID, "password")
    password_field.send_keys(password)
    # 5. Kliknutí na přihlásit (tlačítko typu submit)
    login_button = driver.find_element(By.CSS_SELECTOR, "input[type='submit']")
    login_button.click()

    # --- TADY ZAČÍNÁ TA "PROKLIKÁVACÍ" ČÁST ---
    # Počkej, až se načte hlavní dashboard (např. čekáním na nějaký prvek, co je jen tam)
    folder = wait.until(EC.element_to_be_clickable((By.XPATH, "//a[contains(., 'SIVIN VUT')]")))
    driver.execute_script("arguments[0].click();", folder)
    print("Kliknuto na SIVIN VUT pomocí JavaScriptu.")
    print("Složka SIVIN VUT otevřena.")
    # 1. Získání seznamu jmen čidel z neviditelného inputu
    viewmodel_element = driver.find_element(By.ID, "__dot_viewmodel_root")
    data = json.loads(viewmodel_element.get_attribute("value"))

    # Cesta v JSONu: viewModel -> Scene -> Sections -> první sekce -> Devices
    devices = data["viewModel"]["Scene"]["Sections"][0]["Devices"]
    device_names = [d["DeviceName"] for d in devices]

    print(f"Nalezena čidla: {device_names}")

    for name in device_names:
        print(f"Zpracovávám čidlo: {name}")

        try:
            # 1. Čekáme na zmizení spinneru
            wait.until(EC.invisibility_of_element_located((By.ID, "UpdateProgress")))

            # 2. Kliknutí na čidlo (použijeme JS pro jistotu)
            link = wait.until(
                EC.presence_of_element_located((By.XPATH, f"//a[contains(., '{name}')]"))
                )
            driver.execute_script("arguments[0].click();", link)

            # 3. POČKÁME, až se změní URL nebo načte obsah (klíčový krok)
            time.sleep(3) # Dejme systému čas na vykreslení detailu čidla
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            print("Scrollováno na konec stránky.")
            time.sleep(1)
            # 4. Hledání Excel tlačítka - zkusíme několik cest
            tab_meteo = wait.until(EC.element_to_be_clickable(
                (By.XPATH, "//a[contains(text(), 'Meteorologická data')]"))
                                   )
            driver.execute_script("arguments[0].click();", tab_meteo)
            print("Přepnuto na Meteorologická data.")

            # Počkáme, až se tabulka pod záložkou načte (zmizí spinner)
            wait.until(EC.invisibility_of_element_located((By.ID, "UpdateProgress")))
            time.sleep(2)

            # 2. NAJÍT EXCEL TLAČÍTKO V AKTIVNÍM TABU
            # Hledáme tlačítko s ikonou mdi-file-excel, které JE VIDITELNÉ
            # (Použijeme XPath, který ignoruje ty schované v jiných tabech)
            excel_btns = driver.find_elements(
                By.XPATH, "//button[.//i[contains(@class, 'mdi-file-excel')]]"
                )

            TARGET_BTN = None
            for btn in excel_btns:
                if btn.is_displayed(): # Chceme jen to, které vidíš na obrazovce
                    TARGET_BTN = btn
                    break

            if TARGET_BTN:
                driver.execute_script(
                    "arguments[0].scrollIntoView({block: 'center'});", TARGET_BTN
                    )
                time.sleep(1)
                driver.execute_script("arguments[0].click();", TARGET_BTN)
                print(f"Excel pro {name} odeslán ke stažení.")
                time.sleep(5)
            else:
                print("Viditelné tlačítko Excel nenalezeno.")
            # 3. Počkáme, až se objeví nový soubor a zmizí přípona .crdownload
            # (dočasný soubor Chromu)
            TIMEOUT = 30
            start_time = time.time()
            NEW_FILE = None

            while time.time() - start_time < TIMEOUT:
                current_latest = get_latest_file(download_folder)
                if current_latest and not current_latest.endswith('.crdownload'):
                    NEW_FILE = current_latest
                    break
                time.sleep(1)

            print(f"Stáhnut soubor: {NEW_FILE}")
            # 5. Návrat zpět
            driver.back()

        except ValueError as e:
            print(f"Chyba u čidla {name}: {e}")
            # Pokud se něco pokazí, zkusíme se vrátit na hlavní stránku SIVIN VUT
            driver.get("tvoje_url_s_vypisem_sivin_vut")

    print("Všechna čidla byla zpracována.")
    # Příklad prokliku na ikonku Excelu (budeš muset najít správný selektor po přihlášení)
    # excel_btn = wait.until(EC.element_to_be_clickable((By.CLASS_NAME, "icon-excel")))
    # excel_btn.click()

    time.sleep(5) # Čas na dokončení downloadu

finally:
    driver.quit()
