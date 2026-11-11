"""Запись демонстрации прототипа СППР (практика №8).

Сценарий проходит по интерфейсу ЛПР и дашборду Superset в браузере (Playwright) и записывает видео
окна страницы с поясняющими подписями. Требуются запущенные сервисы (docker compose up -d), пакеты
playwright и imageio-ffmpeg (или системный ffmpeg).
    python tools/record_screencast.py [выходной.mp4]
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
APP = os.environ.get("SPPR_APP_URL", "http://localhost:8501")
SUPERSET = os.environ.get("SUPERSET_URL", "http://localhost:8088")
W, H = 1920, 1080

OVERLAY = """
(() => {
  const init = () => {
    if (document.getElementById('sppr-cap')) return;
    const cap = document.createElement('div');
    cap.id = 'sppr-cap';
    cap.style.cssText = 'position:fixed;left:0;right:0;bottom:0;z-index:2147483647;background:rgba(20,30,45,.93);color:#fff;' +
      'font:500 25px/1.35 Arial,sans-serif;padding:16px 48px;text-align:center;display:none;pointer-events:none';
    document.body.appendChild(cap);
    const cur = document.createElement('div');
    cur.id = 'sppr-cur';
    cur.style.cssText = 'position:fixed;z-index:2147483647;width:22px;height:22px;border-radius:50%;background:rgba(220,60,40,.55);' +
      'border:2px solid #fff;box-shadow:0 0 4px rgba(0,0,0,.5);pointer-events:none;left:-50px;top:-50px;transform:translate(-50%,-50%)';
    document.body.appendChild(cur);
    document.addEventListener('mousemove', e => { cur.style.left = e.clientX + 'px'; cur.style.top = e.clientY + 'px'; }, true);
    try { const saved = sessionStorage.getItem('sppr-cap'); if (saved) { cap.textContent = saved; cap.style.display = 'block'; } } catch (e) {}
  };
  if (document.body) init(); else document.addEventListener('DOMContentLoaded', init);
})();
"""

SLIDE = """<html><body style="margin:0;height:100vh;display:flex;flex-direction:column;justify-content:center;align-items:center;
background:#16263a;color:#fff;font-family:Arial,sans-serif;text-align:center">
<div style="font-size:30px;color:#9fb6d0;margin-bottom:26px">{top}</div>
<div style="font-size:58px;font-weight:700;max-width:1500px;line-height:1.2">{title}</div>
<div style="font-size:30px;margin-top:40px;line-height:1.6;color:#dfe8f2">{body}</div></body></html>"""


class Demo:
    def __init__(self, page):
        self.p = page
        self.pos = (W // 2, H // 2)

    def say(self, text, wait=4.0):
        self.p.evaluate("""t => { try { sessionStorage.setItem('sppr-cap', t); } catch (e) {} const c = document.getElementById('sppr-cap');
                           if (c) { c.textContent = t; c.style.display = t ? 'block' : 'none'; } }""", text)
        self.p.wait_for_timeout(int(wait * 1000))

    def move(self, x, y, pause=0.4):
        self.p.mouse.move(x, y, steps=28)
        self.pos = (x, y)
        self.p.wait_for_timeout(int(pause * 1000))

    def click(self, locator, pause=1.2):
        locator.scroll_into_view_if_needed()
        box = locator.bounding_box()
        self.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        self.p.mouse.click(*self.pos)
        self.p.wait_for_timeout(int(pause * 1000))

    def hover(self, locator, pause=1.0):
        box = locator.bounding_box()
        if box:
            self.move(box["x"] + box["width"] / 2, box["y"] + min(box["height"] / 2, 200), pause)

    def scroll(self, dy, steps=24, pause=0.8):
        self.move(W * 0.62, H * 0.5, 0.1)
        for _ in range(steps):
            self.p.mouse.wheel(0, dy / steps)
            self.p.wait_for_timeout(30)
        self.p.wait_for_timeout(int(pause * 1000))

    def top(self):
        self.scroll(-6000, steps=12, pause=0.4)

    def settle(self, extra=0.8):
        """Ждём, пока Streamlit закончит пересчёт."""
        self.p.wait_for_timeout(500)
        try:
            self.p.wait_for_selector('[data-testid="stStatusWidget"]', state="detached", timeout=60000)
        except Exception:
            pass
        self.p.wait_for_timeout(int(extra * 1000))

    def tab(self, name):
        self.top()
        self.click(self.p.get_by_role("tab", name=name))
        self.settle()

    def scenario(self, name):
        self.click(self.p.locator('[data-testid="stSidebar"] [data-testid="stSelectbox"] [role="combobox"]').first, 0.8)
        self.click(self.p.get_by_role("option", name=name), 0.5)
        self.settle()

    def slider_drag(self, index, fraction):
        """Перетаскивает ползунок боковой панели в положение fraction (0..1) его шкалы."""
        sl = self.p.locator('[data-testid="stSidebar"] [data-testid="stSlider"]').nth(index)
        sl.scroll_into_view_if_needed()
        thumb = sl.locator('[data-testid="stSliderThumbValue"]').first.bounding_box()
        track = sl.locator('[data-testid="stSliderTickBar"]').first.bounding_box()
        y = thumb["y"] + thumb["height"] + 12
        self.move(thumb["x"] + thumb["width"] / 2, y)
        self.p.mouse.down()
        self.p.mouse.move(track["x"] + track["width"] * fraction, y, steps=30)
        self.p.wait_for_timeout(300)
        self.p.mouse.up()
        self.settle()

    def slide(self, top, title, body, caption="", wait=6.0):
        self.p.set_content(SLIDE.format(top=top, title=title, body=body))
        self.p.evaluate(OVERLAY)
        self.say(caption, wait)


def superset_credentials():
    vals = {}
    for line in (ROOT / "bi" / ".env").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            vals[k.strip()] = v.strip()
    return vals.get("SUPERSET_ADMIN_USER", "admin"), vals["SUPERSET_ADMIN_PASSWORD"]


def run(d):
    p = d.p
    d.slide("Сквозная работа по дисциплине «Системы поддержки принятия решений»",
            "СППР выбора поставщиков оборудования<br>для диспетчерских комплексов",
            "Новосельцев Андрей Алексеевич, группа К4241<br>Демонстрация работающего прототипа",
            "Прототип объединяет результаты семи практик и запускается одной командой: docker compose up", 7)

    p.goto(APP, wait_until="networkidle")
    p.wait_for_selector("text=Кого выбрать", timeout=120000)
    d.settle(1.5)
    d.say("Интерфейс директора. Слева - параметры решения: бюджет, сроки, требования к комплексу, отношение к риску", 5)
    d.hover(p.locator('[data-testid="stSidebar"]'), 1.5)
    d.say("Главный экран - рекомендация: полезность плана, ожидаемые затраты с учётом риска и худшие 5 % исходов", 5)
    d.hover(p.locator('[data-testid="stMetric"]').nth(1), 1.5)
    d.say("Кого выбрать в каждой категории, сколько комплексов закупить, резервный поставщик и объяснение выбора", 6)
    d.hover(p.get_by_role("heading", name="Кого выбрать"), 2)
    d.say("Справа - готовый список действий для директора с указанием, из какого модуля взято основание", 6)
    d.hover(p.get_by_role("heading", name="Что сделать директору"), 2)

    d.tab("Критерии и рейтинг")
    d.say("Практика 2. Метод анализа иерархий: веса семи критериев и рейтинг допустимых поставщиков", 5)
    d.scroll(520)
    d.say("Рейтинг пересчитывается под сценарий директора; согласованность суждений проверена (ОС = 0,012)", 4.5)

    d.tab("Риски")
    d.say("Практика 3. Стратегии закупки при неопределённом курсе и сроках: критерии Байеса, Вальда, Сэвиджа, Гурвица", 5.5)
    d.scroll(380)
    d.say("Дерево решений и имитация методом Монте-Карло: закупка заранее дешевле и надёжнее оплаты по факту", 6)

    d.tab("Оптимальный план")
    d.say("Практика 4. Оптимизационная модель (PuLP): сколько комплексов комплектовать у каждого поставщика", 5.5)
    d.scroll(520)
    d.say("Граница «затраты - полезность»: красная точка - текущий план при выбранных параметрах", 5)

    d.tab("База знаний")
    d.say("Практика 5. База знаний: онтология и 15 правил. Для каждой модели - заключение и сработавшие правила", 6)
    d.scroll(420)
    d.click(p.locator("summary").filter(has_text="Продукционные правила"), 1.0)
    d.scroll(420)
    d.say("Правила ЕСЛИ - ТО продублированы на языке SWRL; онтологию можно скачать и открыть в Protégé", 5.5)

    d.tab("Прогноз и дашборд")
    d.say("Практика 6. Прогноз курса доллара на 13 недель с интервалами 80 и 95 % и точность четырёх моделей", 6.5)

    # сценарии «что если»
    d.tab("Рекомендация")
    d.say("Теперь сценарии. Директор меняет параметры - система заново выполняет всю цепочку расчётов", 4.5)
    d.slider_drag(0, (13.0 - 10.5) / 3.5)
    d.say("Бюджет увеличен до 13 млн руб.: план и затраты пересчитаны, изменились определяющие ограничения", 6)
    d.scenario("Импортозамещение")
    d.say("Требование импортозамещения: допустимого плана нет. База знаний объясняет причину - правило R14", 6.5)
    d.tab("База знаний")
    d.say("Зарубежные модели отсеяны правилом R7: в категориях КВМ и ПК не осталось допустимых альтернатив", 6)
    d.scenario("Типовой комплекс")
    d.click(p.locator('[data-testid="stSidebar"]').get_by_text("АВР установлен перед ИБП"), 0.5)
    d.settle()
    d.say("АВР питает нагрузку напрямую: Уралэнерготел недопустим из-за времени переключения (правило R3)", 6)
    d.tab("Рекомендация")
    d.say("Рекомендация изменилась: в категории АВР остался единственный допустимый поставщик - Elemy", 6)
    d.scenario("Осторожный директор")
    d.say("Осторожный директор: вес надёжности и санкционного риска выше - меняются уверенность и объяснения", 6)

    # дашборд Superset
    user, password = superset_credentials()
    p.goto(f"{SUPERSET}/login/", wait_until="networkidle")
    d.say("Практика 6. Дашборд в Apache Superset над витриной данных прототипа", 2.5)
    p.locator('input[type="text"]').first.fill(user)
    p.locator('input[type="password"]').first.fill(password)
    p.locator('button[type="submit"]').first.click()
    p.wait_for_load_state("networkidle")
    p.goto(f"{SUPERSET}/superset/dashboard/sppr/?standalone=1", wait_until="networkidle")
    p.wait_for_timeout(9000)
    d.say("Показатели, курс с прогнозом и интервалом, прогноз стоимости плана закупки", 6)
    d.move(700, 520, 1.0)
    p.evaluate("document.scrollingElement.scrollBy({top: 640, behavior: 'smooth'})")
    p.wait_for_timeout(4000)
    d.say("План закупки по категориям и поставщикам, индексы цен производителей Росстата", 5.5)
    p.evaluate("document.scrollingElement.scrollBy({top: 700, behavior: 'smooth'})")
    p.wait_for_timeout(3500)
    d.say("Предупреждения базы знаний и точность моделей прогноза", 5.5)

    p.goto(APP, wait_until="networkidle")
    p.wait_for_selector("text=Кого выбрать", timeout=120000)
    d.settle(1.0)
    d.tab("О системе")
    d.say("Архитектура: семь модулей на Python, общий интерфейс и дашборд. Ограничения прототипа указаны явно", 7)
    d.slide("Итог", "Работающий прототип СППР",
            "Рекомендация: у основного поставщика в категории - 6 комплексов из 10, у второго - 4,<br>"
            "закупку провести заранее, закупку HP согласовать<br><br>"
            "github.com/AndrewFalse/sppr-supplier-selection<br>docker compose up -d --build", "", 8)


def ffmpeg_bin():
    """Системный ffmpeg, если работает, иначе - из пакета imageio-ffmpeg."""
    exe = shutil.which("ffmpeg")
    if exe and subprocess.run([exe, "-version"], capture_output=True).returncode == 0:
        return exe
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def main():
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "screencast.mp4").expanduser()
    tmp = Path(tempfile.mkdtemp(prefix="sppr_video_"))
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, channel=os.environ.get("SPPR_BROWSER_CHANNEL") or None)
        ctx = browser.new_context(viewport={"width": W, "height": H}, locale="ru-RU", color_scheme="light",
                                  record_video_dir=str(tmp), record_video_size={"width": W, "height": H})
        ctx.add_init_script(OVERLAY)
        page = ctx.new_page()
        try:
            run(Demo(page))
        finally:
            ctx.close()
            browser.close()
    src = next(tmp.glob("*.webm"))
    subprocess.run([ffmpeg_bin(), "-y", "-loglevel", "error", "-i", str(src), "-c:v", "libx264", "-preset", "slow", "-crf", "20",
                    "-pix_fmt", "yuv420p", "-r", "25", "-movflags", "+faststart", str(out)], check=True)
    shutil.rmtree(tmp, ignore_errors=True)
    print("видео:", out)


if __name__ == "__main__":
    main()
