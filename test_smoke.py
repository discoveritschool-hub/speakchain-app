#!/usr/bin/env python3
"""
test_smoke.py — сітка, крізь яку не проліземо ні ти, ні Клод.

ЗАПУСК
──────
    python3 test_smoke.py

Зелено → лий у прод.  Червоно → ось що зламано, рядок вказано.

НАВІЩО
──────
Staging-бота немає. Значить, ці тести — ЄДИНЕ, що стоїть між
помилкою і живими людьми.

Кожен тест тут — це баг, який РЕАЛЬНО був спійманий і який
НЕ знайшовся б ручною перевіркою в Telegram:

  • datetime не імпортовано → NameError рівно в момент тиску кнопки
  • JS hoisting → ін'єкція не працювала б, а статика мовчала
  • ov-invite-host замість -body → зник би хрестик закриття
  • run_repeating фаза → нудж о 21:38 замість обіцяних 21:00
  • _need_start_kb визначено НИЖЧЕ за виклик

ЯК ЧИТАЄ КОД
────────────
НЕ імпортує bot.py — він тягне Telegram, Postgres, ключі.
Читає як ТЕКСТ і AST. Тому працює в CI без секретів і бази.

ЯК ДОДАВАТИ НОВИЙ ТЕСТ
──────────────────────
Знайшов баг → напиши сюди перевірку, яка б його спіймала.
Тести накопичуються. Через місяць — сітка.
"""

import ast
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).parent
BOT = ROOT / "bot.py"
DEMO = ROOT / "demo_flow.py"


def _find_shell():
    """
    Знаходить оболонку, не покладаючись на точну назву.

    РЕАЛЬНИЙ ВИПАДОК: тест шукав рівно 'index_v2.html', не знайшов —
    і МОВЧКИ пропустив усі перевірки оболонки, показавши «можна лити».
    Тепер шукаємо за ознакою (файл із `const APPS`), а не за назвою.
    Регістр, дефіс, підтека — байдуже.
    """
    # 1. очевидні кандидати в корені
    for name in ("index_v2.html", "index.html", "index_v2.htm"):
        p = ROOT / name
        if p.exists():
            return p
    # 2. будь-який .html, що містить `const APPS` — це вона
    for p in sorted(ROOT.rglob("*.htm*")):
        if any(part in (".git", "node_modules", "__pycache__")
               for part in p.parts):
            continue
        try:
            head = p.read_text(encoding="utf-8", errors="ignore")[:400_000]
        except Exception:
            continue
        if "const APPS" in head:
            return p
    return ROOT / "index_v2.html"      # не знайшли — шлях для повідомлення


SHELL = _find_shell()

FAILS = []
PASSES = []


def ok(msg):
    PASSES.append(msg)
    print(f"  \033[32m✓\033[0m {msg}")


def fail(msg):
    FAILS.append(msg)
    print(f"  \033[31m✗ {msg}\033[0m")


def section(name):
    print(f"\n\033[1m{name}\033[0m")


# ══════════════════════════════════════════════════════════════
# 1. СИНТАКСИС — найдешевший тест, ловить найдурніші помилки
# ══════════════════════════════════════════════════════════════
def test_python_syntax():
    section("Python — синтаксис")
    for f in ROOT.glob("*.py"):
        if f.name == "test_smoke.py":
            continue
        try:
            ast.parse(f.read_text(encoding="utf-8"))
            ok(f"{f.name}")
        except SyntaxError as e:
            fail(f"{f.name} р.{e.lineno}: {e.msg}")


# ══════════════════════════════════════════════════════════════
# 2. ІМПОРТИ — баг, що впав би в рантаймі при тиску кнопки
# ══════════════════════════════════════════════════════════════
def test_imports_exist():
    """
    РЕАЛЬНИЙ БАГ: у demo_flow.py використали datetime.now(), але
    `from datetime import datetime` не було. Синтаксис ВАЛІДНИЙ —
    ast.parse() мовчить. NameError вилазить рівно в ту мить, коли
    людина тисне кнопку після демо. Найгірше можливе місце.
    """
    section("Python — кожне ім'я має імпорт або визначення")
    for f in ROOT.glob("*.py"):
        if f.name == "test_smoke.py":
            continue
        src = f.read_text(encoding="utf-8")
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue

        defined = set(dir(__builtins__)) | {"__name__", "__file__", "__doc__"}
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                for a in n.names:
                    defined.add(a.asname or a.name.split(".")[0])
            elif isinstance(n, ast.ImportFrom):
                for a in n.names:
                    defined.add(a.asname or a.name)
            elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                defined.add(n.name)
            elif isinstance(n, ast.Assign):
                for t in n.targets:
                    if isinstance(t, ast.Name):
                        defined.add(t.id)
            elif isinstance(n, (ast.arg, ast.Name)) and isinstance(
                getattr(n, "ctx", None), ast.Store
            ):
                defined.add(getattr(n, "id", getattr(n, "arg", "")))
            elif isinstance(n, ast.arg):
                defined.add(n.arg)
            elif isinstance(n, ast.ExceptHandler) and n.name:
                defined.add(n.name)
            elif isinstance(n, ast.Global):
                defined.update(n.names)

        # Перевіряємо тільки «підозрілі» — ті, що часто забувають
        WATCH = {"datetime", "timezone", "timedelta", "time", "json", "re",
                 "asyncio", "logging", "os", "random", "InlineKeyboardButton",
                 "InlineKeyboardMarkup", "Update", "ContextTypes"}
        used = {n.id for n in ast.walk(tree)
                if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
        missing = (used & WATCH) - defined
        if missing:
            fail(f"{f.name}: використано, але не імпортовано → {sorted(missing)}")
        else:
            ok(f"{f.name}")


# ══════════════════════════════════════════════════════════════
# 3. ПОРЯДОК ВИЗНАЧЕНЬ — функція мусить бути ВИЩЕ за виклик
# ══════════════════════════════════════════════════════════════
def test_helper_order():
    """
    РЕАЛЬНИЙ БАГ: _need_start_kb визначили на р.18555, а викликали
    з settings_reset на р.18196. Python терпить (виклик у рантаймі),
    але це крихко — один рефакторинг, і NameError.

    Так само _is_user_hour: job_streak_rescue (р.4411) стояв ВИЩЕ
    за визначення (р.5469).
    """
    section("Python — хелпери визначені ВИЩЕ за виклики")
    if not BOT.exists():
        return
    src = BOT.read_text(encoding="utf-8")
    lines = src.split("\n")

    HELPERS = ["_need_start_kb", "_is_user_hour", "_user_hour_now",
               "_secs_to_next_hour"]
    for h in HELPERS:
        defs = [i for i, l in enumerate(lines, 1) if l.startswith(f"def {h}(")]
        if not defs:
            continue
        if len(defs) > 1:
            fail(f"{h}: {len(defs)} визначень (має бути 1) — р.{defs}")
            continue
        d = defs[0]
        calls = [i for i, l in enumerate(lines, 1)
                 if f"{h}(" in l and not l.strip().startswith(("def ", "#"))]
        bad = [c for c in calls if c < d]
        if bad:
            fail(f"{h} визначено р.{d}, але викликано ВИЩЕ — р.{bad}")
        else:
            ok(f"{h}: def р.{d}, {len(calls)} викликів — усі нижче")


# ══════════════════════════════════════════════════════════════
# 4. КНОПКИ — кожен callback_data мусить мати хендлер
# ══════════════════════════════════════════════════════════════
def test_callbacks_have_handlers():
    """
    МЕРТВА КНОПКА — найтихіший баг. Людина тисне, нічого не стається,
    вона тисне ще раз, потім іде. У логах — нічого.

    Наприклад: open_buddy викликався в мініапі, але бот про нього
    НЕ ЗНАВ — жодного хендлера. Кнопка була мертва двічі.
    """
    section("Кнопки — кожен callback має хендлер")
    if not BOT.exists():
        return
    bot_src = BOT.read_text(encoding="utf-8")

    # Усі зареєстровані патерни
    patterns = re.findall(r'CallbackQueryHandler\([^,]+,\s*pattern=["\']([^"\']+)["\']', bot_src)
    # Плюс мапи DEMO_CALLBACKS тощо
    mapped = set(re.findall(r'_CALLBACKS\[["\']([a-z_0-9]+)["\']\]', bot_src))
    # Плюс elif q.data == "..."
    elifs = set(re.findall(r'q\.data\s*==\s*["\']([a-z_0-9]+)["\']', bot_src))
    if DEMO.exists():
        mapped |= set(re.findall(r'_CALLBACKS\[["\']([a-z_0-9]+)["\']\]',
                                 DEMO.read_text(encoding="utf-8")))

    def has_handler(cd):
        if cd in mapped or cd in elifs:
            return True
        return any(re.match(p, cd) for p in patterns)

    # Збираємо всі callback_data з коду і з оболонки
    srcs = {"bot.py": bot_src}
    if DEMO.exists():
        srcs["demo_flow.py"] = DEMO.read_text(encoding="utf-8")

    dead = []
    total = 0
    for name, src in srcs.items():
        for cd in set(re.findall(r'callback_data=f?["\']([a-z_0-9{}]+)["\']', src)):
            if "{" in cd:      # f-string, напр. start_challenge_{flow_type}
                continue
            total += 1
            if not has_handler(cd):
                dead.append(f"{cd} ({name})")

    if dead:
        for d in sorted(dead):
            fail(f"МЕРТВА КНОПКА: {d} — жодного хендлера")
    else:
        ok(f"усі {total} callback_data мають хендлер")


# ══════════════════════════════════════════════════════════════
# 5. ЖОДНОГО «Натисни /start» — намір людини не має згорати
# ══════════════════════════════════════════════════════════════
def test_no_type_the_command():
    """
    Пік емоції — і людину просять НАБРАТИ КОМАНДУ.
    Telegram навіть не робить /start клікабельним у реченні.
    Замість цього має бути кнопка.
    """
    section("UX — жодного «Натисни /start» у текстах")
    if not BOT.exists():
        return          # репо оболонки — тут бота немає
    hits = []
    for f in (BOT, DEMO):
        if not f.exists():
            continue
        for i, l in enumerate(f.read_text(encoding="utf-8").split("\n"), 1):
            if l.strip().startswith("#"):
                continue
            if re.search(r'["\'].*[Нн]атисни /start', l) or \
               re.search(r'["\'].*почни челендж\. /start', l):
                hits.append(f"{f.name} р.{i}")
    if hits:
        for h in hits:
            fail(f"«Натисни /start» замість кнопки: {h}")
    else:
        ok("замість команд — кнопки")


# ══════════════════════════════════════════════════════════════
# 6. ЧАС ЛЮДИНИ — кожен пояс отримує РІВНО 1 раз на добу
# ══════════════════════════════════════════════════════════════
def test_timezone_exactly_once():
    """
    Джоби крутяться ЩОГОДИНИ і фільтрують за годиною людини.
    Ризик: людина отримає 0 разів (тихо зникла) або 2+ (спам).

    Плюс: run_daily НЕ МОЖЕ лишитись у цих джобах — інакше фільтр
    вимкне розсилки для 23 з 24 поясів.
    """
    section("Час — кожен пояс рівно 1× на добу")
    if not BOT.exists():
        return
    src = BOT.read_text(encoding="utf-8")

    TZ_JOBS = ["job_challenge_evening", "job_challenge_video_delivery",
               "job_streak_rescue", "job_premium_peek",
               "job_challenge_winback", "job_challenge_day7"]

    # 6a. розклад — run_repeating, НЕ run_daily
    for j in TZ_JOBS:
        if re.search(rf"run_daily\({j}\b", src):
            fail(f"{j}: run_daily → шле за часом СЕРВЕРА (треба run_repeating + фільтр)")
        elif re.search(rf"run_repeating\({j}\b", src):
            ok(f"{j}: run_repeating")
        else:
            fail(f"{j}: не знайдено в розкладі")

    # 6b. фільтр всередині джоба
    for j in TZ_JOBS:
        i = src.find(f"async def {j}(")
        if i < 0:
            continue
        body = src[i:i + 3000]
        if "_is_user_hour(" not in body:
            fail(f"{j}: немає фільтра _is_user_hour → шле за часом СЕРВЕРА")

    # 6c. математика: (h + off) % 24 == target має РІВНО 1 розв'язок
    for off in (-8, -4, 0, 2, 5, 10, 12, 99, -30):
        hits = [h for h in range(24) if (h + off) % 24 == 21]
        if len(hits) != 1:
            fail(f"utc_offset={off}: спрацює {len(hits)}× на добу!")
    ok("математика: будь-який offset → рівно 1 збіг за добу")


# ══════════════════════════════════════════════════════════════
# 7. ОБІЦЯНКА — якщо бот каже «21:00 за твоїм часом», хай тримає
# ══════════════════════════════════════════════════════════════
def test_promise_kept():
    section("Обіцянка — «21:00 за твоїм часом»")
    if not BOT.exists():
        return
    src = BOT.read_text(encoding="utf-8")
    promises = re.findall(r'за твоїм часом', src)
    if not promises:
        ok("обіцянки немає — нічого тримати")
        return
    ev = src.find("async def job_challenge_evening")
    if ev > 0 and "_is_user_hour(" not in src[ev:ev + 3000]:
        fail("бот обіцяє «21:00 за твоїм часом», але вечірній нудж — за часом СЕРВЕРА")
    else:
        ok(f"обіцянка є ({len(promises)}×) і вечірній нудж її тримає")


# ══════════════════════════════════════════════════════════════
# 8. ОБОЛОНКА — APPS JSON + JS кожного мініапа
# ══════════════════════════════════════════════════════════════
def _extract_apps(src):
    i = src.find("const APPS")
    if i < 0:
        return None, 0, 0
    j = src.find("{", i)
    d = 0
    for k in range(j, len(src)):
        if src[k] == "{":
            d += 1
        elif src[k] == "}":
            d -= 1
            if d == 0:
                break
    return src[j:k + 1], j, k + 1


def test_shell_apps():
    section("Оболонка — APPS і JS мініапів")
    import os
    if os.environ.get("SKIP_SHELL"):
        print("  (SKIP_SHELL=1 — оболонка в іншому репо)")
        return
    if not SHELL.exists():
        return          # вже зафейлено в test_files_present()
    src = SHELL.read_text(encoding="utf-8")

    raw, _, _ = _extract_apps(src)
    if raw is None:
        fail("const APPS не знайдено")
        return
    try:
        apps = json.loads(raw)
        ok(f"APPS JSON валідний — {len(apps)} мініапів")
    except Exception as e:
        fail(f"APPS JSON зламано: {e}")
        return

    if not _has_node():
        fail("node не знайдено — JS мініапів НЕ ПЕРЕВІРЕНО. "
             "Додай actions/setup-node@v4 у smoke.yml")
        return

    # 8a. JS кожного мініапа парситься
    bad = []
    for name, app in apps.items():
        if not _js_ok(app.get("js", "")):
            bad.append(name)
    if bad:
        fail(f"JS зламано: {bad}")
    else:
        ok(f"JS усіх {len(apps)} мініапів парситься")

    # 8b. JS оболонки
    # The APPS JSON contains complete embedded HTML/JS modules, including
    # literal ``<script>`` text. rfind("<script>") therefore starts inside a
    # module string and reports a false syntax error. Parse top-level script
    # blocks and select the one that owns the shell registry.
    scripts = re.findall(r"<script(?:\s[^>]*)?>(.*?)</script>", src, re.S | re.I)
    shell_js = next((script for script in reversed(scripts) if "const APPS" in script), "")
    if _js_ok(shell_js):
        ok("JS оболонки парситься")
    else:
        fail("JS оболонки зламано")


def test_pwa_identity_handoff():
    """Browser login must hydrate the shell before its first payload request."""
    section("PWA — Google/Telegram identity handoff")
    if not SHELL.exists():
        return
    src = SHELL.read_text(encoding="utf-8")
    load_start = src.find("async function load(scr){")
    load_end = src.find("function showOfflineBanner", load_start)
    load_src = src[load_start:load_end] if load_start >= 0 and load_end > load_start else ""
    if "await window.SC_PWA.ready" not in load_src:
        fail("load() не чекає PWA-сесію перед перевіркою UID")
    elif load_src.find("await window.SC_PWA.ready") > load_src.find("if(!UID){", 50):
        fail("PWA-сесія читається запізно — після anonymous-перевірки")
    elif "session?.userId" not in load_src:
        fail("UID оболонки не підхоплюється з PWA-сесії")
    else:
        ok("Google/PWA userId підхоплюється до першого payload-запиту")

    pwa = (ROOT / "pwa.js").read_text(encoding="utf-8")
    if "AbortController" not in pwa or "session_timeout" not in pwa:
        fail("PWA-вхід не має тайм-ауту та зрозумілого повідомлення при недоступному backend")
    elif "getBoundingClientRect().width" not in pwa:
        fail("Google-кнопка не підлаштовується під ширину вікна")
    else:
        ok("Google-вхід має тайм-аут, видиму помилку й адаптивну кнопку")


def _has_node():
    try:
        subprocess.run(["node", "--version"], capture_output=True, timeout=5)
        return True
    except Exception:
        return False


def _js_ok(js):
    tmp = ROOT / ".smoke_tmp.js"
    try:
        tmp.write_text(js, encoding="utf-8")
        r = subprocess.run(["node", "--check", str(tmp)],
                           capture_output=True, timeout=20)
        return r.returncode == 0
    except Exception:
        return False
    finally:
        tmp.unlink(missing_ok=True)


# ══════════════════════════════════════════════════════════════
# 9. ОБОЛОНКА — роутер живий, додаток не гасне
# ══════════════════════════════════════════════════════════════
def test_shell_router():
    """
    РЕАЛЬНИЙ БАГ 1: act() робив TG.close() → бот слав кнопку →
      кнопка відкривала цей самий додаток назад. Коло.

    РЕАЛЬНИЙ БАГ 2 (страшніший): ін'єкцію поставили ПЕРЕД кодом
      мініапа. JS hoisting — перемагає ОСТАННЯ function declaration.
      Мініап перекривав ін'єкцію своєю мертвою maAction.
      Патч не працював би ВЗАГАЛІ, а всі статичні тести були зелені.

    РЕАЛЬНИЙ БАГ 3: хост оверлея — ov-invite-HOST, не -body.
      Було б attachShadow на контейнері → зник би хрестик закриття.
    """
    section("Оболонка — роутер")
    import os
    if os.environ.get("SKIP_SHELL") or not SHELL.exists():
        return          # вже зафейлено / свідомо пропущено
    src = SHELL.read_text(encoding="utf-8")
    scripts = re.findall(r"<script(?:\s[^>]*)?>(.*?)</script>", src, re.S | re.I)
    shell_js = next((script for script in reversed(scripts) if "const APPS" in script), "")

    # 9a. act() без TG.close()
    a = shell_js.find("async function act(a,x){")
    if a < 0:
        fail("act() оболонки не знайдено")
        return
    end = shell_js.find("\nasync function ", a + 10)
    body = shell_js[a:end if end > a else a + 900]
    if "close" in body:
        fail("act() має TG.close() → додаток гасне, бот шле кнопку назад. КОЛО")
    else:
        ok("act() без TG.close() — додаток не гасне")

    # 9b. sync.py не затре роутер (APPS має лишитись чистим)
    raw, _, _ = _extract_apps(src)
    if raw and "SHELL_TABS" in raw:
        fail("роутер УСЕРЕДИНІ APPS → наступний `sync.py` його ЗАТРЕ")
    else:
        ok("роутер поза APPS — sync.py безпечний")

    # 9c. ін'єкція ПІСЛЯ коду мініапа (hoisting!)
    m = re.search(r"new Function\([^)]*\)\s*,?\s*\n?\s*(.*?)\)\(fD,fW,fL", shell_js, re.S)
    if "__act" in shell_js:
        inj = shell_js.find("__act(action, extra")
        code = shell_js.find("APPS[id].js")
        if 0 < inj < code:
            fail("ін'єкція ПЕРЕД APPS[id].js → hoisting: мініап перекриє її. НЕ ПРАЦЮЄ")
        else:
            ok("ін'єкція ПІСЛЯ коду мініапа (hoisting враховано)")

    # 9d. цілі роутера існують як екрани
    ids = set(re.findall(r'id="(s-[a-z]+|ov-[a-z]+)"', src))
    tabs = re.search(r"SHELL_TABS\s*=\s*\{(.*?)\};", shell_js, re.S)
    ovs = re.search(r"SHELL_OVERLAYS\s*=\s*\{(.*?)\};", shell_js, re.S)
    targets = set()
    if tabs:
        targets |= set(re.findall(r"'(s-[a-z]+)'", tabs.group(1)))
    if ovs:
        targets |= set(re.findall(r"'(ov-[a-z]+)'", ovs.group(1)))
    missing = targets - ids
    if missing:
        fail(f"роутер веде на неіснуючі екрани: {sorted(missing)}")
    elif targets:
        ok(f"усі {len(targets)} цілей роутера існують")

    # 9e. оверлеї монтуються у *-host, не *-body
    raw, _, _ = _extract_apps(src)
    mounted_apps = set(json.loads(raw)) if raw else set()
    for ov in set(re.findall(r"'(ov-[a-z]+)'", ovs.group(1) if ovs else "")):
        # Plain shell overlays (for example ov-plans) render directly and do
        # not attach Shadow DOM. Only embedded APPS require a dedicated host.
        if ov not in mounted_apps:
            continue
        if f'id="{ov}-host"' not in src:
            fail(f"{ov}: немає {ov}-host → attachShadow на контейнері, зникне хрестик ×")


# ══════════════════════════════════════════════════════════════
def test_files_present():
    """
    ГОЛОВНИЙ ТЕСТ. Без нього решта — театр.

    РЕАЛЬНИЙ ВИПАДОК: index_v2.html не було в репо. Тест мовчки
    пропустив УСІ перевірки оболонки (APPS, hoisting, TG.close(),
    sync.py) — і показав «✅ можна лити». Зелена галочка БРЕХАЛА.

    Тест, який зеленіє, коли йому нічого перевіряти, ГІРШИЙ
    за відсутність тесту: він дає фальшиву впевненість.

    Тому: файлу немає → ЧЕРВОНИЙ. Крапка.

    ЯКЩО ОБОЛОНКА ЖИВЕ В ІНШОМУ РЕПО — постав змінну оточення:
        SKIP_SHELL=1 python3 test_smoke.py
    І заведи для того репо ОКРЕМИЙ smoke.yml. Мовчазний пропуск —
    не варіант.
    """
    section("Файли на місці")
    import os

    # Тест живе у ДВОХ репо:
    #   • репо бота     → bot.py + demo_flow.py (SKIP_SHELL=1)
    #   • репо оболонки → index_v2.html
    # Визначаємо, де ми, за наявністю bot.py. Але якщо НІ бота, НІ
    # оболонки — це помилка: тест ні до чого не причепився.
    has_bot = BOT.exists()
    has_shell = SHELL.exists()

    if has_bot:
        ok("bot.py")
        if DEMO.exists():
            ok("demo_flow.py")
        else:
            fail("demo_flow.py НЕ ЗНАЙДЕНО — перевірки демо не спрацюють")
    elif not has_shell and not os.environ.get("SKIP_SHELL"):
        fail("НІ bot.py, НІ оболонки — тест ні до чого не причепився. "
             "Поклади test_smoke.py у корінь репо")
        return

    if os.environ.get("SKIP_SHELL"):
        ok("index_v2.html — SKIP_SHELL=1, оболонка в іншому репо (там свій CI)")
    elif SHELL.exists():
        rel = SHELL.relative_to(ROOT)
        ok(f"оболонка: {rel}")
    else:
        htmls = [p.name for p in ROOT.rglob("*.htm*")
                 if ".git" not in p.parts][:12]
        fail("ОБОЛОНКУ НЕ ЗНАЙДЕНО (шукав файл із `const APPS`) → перевірки "
             "APPS/hoisting/TG.close/sync.py НЕ ВИКОНАНО. "
             f"HTML у репо: {htmls or 'жодного'}. "
             "Якщо оболонка в іншому репо — постав SKIP_SHELL=1")


def test_analytics_dashboards():
    """Аналітичні екрани мають містити нові соціальні та AI-зрізи."""
    section("Аналітичні дашборди — соціальна воронка й AI-витрати")
    files = {
        "admin_analytics.html": (
            "function renderSpeakingSocial()",
            "data.social",
            "by_feature",
            "by_provider",
            "by_model",
            "by_student",
            "provider_sync",
        ),
        "strategy_dashboard.html": (
            'data-k="was"',
            'id="socialfunnelbars"',
            "LIVE_SOCIAL",
            "function buildSocialFunnel()",
            "PWA + Telegram + спільна авторизація",
            "Redis і PostgreSQL у production",
            "Навантажувальне тестування",
            "@media(min-width:921px) and (max-height:720px)",
        ),
    }
    for filename, markers in files.items():
        path = ROOT / filename
        if not path.exists():
            fail(f"{filename} не знайдено")
            continue
        src = path.read_text(encoding="utf-8")
        missing = [marker for marker in markers if marker not in src]
        if missing:
            fail(f"{filename}: бракує блоків {missing}")
        else:
            ok(f"{filename}: потрібні аналітичні блоки на місці")

        if _has_node():
            scripts = re.findall(r"<script[^>]*>(.*?)</script>", src, re.S | re.I)
            for index, script in enumerate(scripts, 1):
                if script.strip() and not _js_ok(script):
                    fail(f"{filename}: JavaScript у script #{index} не парситься")
                    break
            else:
                ok(f"{filename}: JavaScript парситься")


def test_friends_stable_layers():
    """Стабільні підвкладки й робочі переходи «Друзів» не мають зникнути."""
    section("Друзі — три рівні, матч, виклики, естафети й профілі")
    if not SHELL.exists():
        fail("Не знайдено оболонку для перевірки вкладки «Друзі»")
        return
    src = SHELL.read_text(encoding="utf-8")
    markers = (
        '<div class="screen" id="s-social">',
        'class="friends-value-card"',
        "+20% XP на 7 днів",
        "+15 XP і +1 ланка",
        "act('chain_invite_screen')",
        "openFriendsSection('challenges')",
        "openFriendsSection('people')",
        'id="soc-tab-feed"',
        'id="soc-tab-challenges"',
        'id="soc-tab-people"',
        'onclick="startLiveMatch()"',
        'onclick="openSocialComposer({mode:\'challenge\'})"',
        'onclick="startRelay()"',
        "function socialTab(tab)",
        "async function openStudentProfile(uid)",
        "async function startLiveMatch()",
        "function startRelay()",
        'onclick="openLotteryTickets()"',
        "async function openLotteryTickets()",
    )
    missing = [marker for marker in markers if marker not in src]
    if missing:
        fail(f"Вкладка «Друзі»: бракує механік {missing}")
    else:
        ok("стабільні рівні й переходи «Друзів» на місці")


def test_profile_lottery_ux():
    """Лотерея живе у профілі, показує прогрес і візуальні квитки."""
    section("Профіль — лотерея, 100 ланок і візуальні квитки")
    if not SHELL.exists():
        fail("Не знайдено оболонку для перевірки лотереї")
        return
    src = SHELL.read_text(encoding="utf-8")
    markers = (
        'id="profile-lottery"',
        "100 ланок = 1 квиток",
        'id="ov-lottery"',
        'id="lottery-overlay-buy"',
        "function lotteryTicketHtml(ticket,index)",
        'class="ticket-card"',
        "lottery_links",
        "links_needed",
        "buyLotteryTicket(",
        "openLotteryTickets()",
    )
    missing = [marker for marker in markers if marker not in src]
    if missing:
        fail(f"Лотерея у профілі: бракує механік {missing}")
        return

    home_start = src.find('<div class="screen on" id="s-home">')
    home_end = src.find('<div class="screen" id="s-buddy">', home_start)
    home = src[home_start:home_end] if home_start >= 0 and home_end > home_start else ""
    if "Лотерея SpeakChain" in home or "openLotteryTickets()" in home:
        fail("Лотерея знову з'явилась на «Сьогодні» замість Профілю")
    else:
        ok("лотерея у Профілі; прогрес, купівля й колекція квитків на місці")


def test_production_assets_and_browser_chainy_auth():
    """Production-only regressions: case-sensitive assets and standalone PWA auth."""
    section("Production assets — Chainy, tokens and browser session")
    avatar = ROOT / "Chainy.png"
    if not avatar.exists() or avatar.stat().st_size < 10_000:
        fail("Chainy.png відсутній або знову порожній")
    elif avatar.read_bytes()[:8] != b"\x89PNG\r\n\x1a\n":
        fail("Chainy.png не є валідним PNG")
    else:
        ok("Chainy.png — валідний production PNG")

    buddy = (ROOT / "speaking_buddy.html").read_text(encoding="utf-8")
    shell = SHELL.read_text(encoding="utf-8") if SHELL.exists() else ""
    if 'src="pwa.js"' not in buddy or "window.SC_PWA?.ready" not in buddy:
        fail("standalone Chainy не підключає браузерну PWA-сесію")
    else:
        ok("standalone Chainy підключає браузерну PWA-сесію")
    if "chainy.png" in buddy or "chainy.png" in shell:
        fail("залишилось посилання з неправильним регістром chainy.png")
    else:
        ok("усі посилання використовують Chainy.png")

    bad_tokens = []
    for name in ("social_invite.html", "speakchain_prototype.html"):
        path = ROOT / name
        if path.exists() and '/static/tokens.css' in path.read_text(encoding="utf-8"):
            bad_tokens.append(name)
    if bad_tokens:
        fail(f"неправильний абсолютний tokens.css у {bad_tokens}")
    else:
        ok("standalone tokens.css використовує Pages-сумісний шлях")

    worker = (ROOT / "sw.js").read_text(encoding="utf-8")
    cache_match = re.search(r"const CACHE = 'speakchain-shell-v(\d+)'", worker)
    if "'./Chainy.png'" not in worker or not cache_match or int(cache_match.group(1)) < 10:
        fail("service worker не оновлює/не кешує аватар Chainy")
    else:
        ok("service worker оновлює і кешує Chainy")

    root_entry = ROOT / "index.html"
    root_text = root_entry.read_text(encoding="utf-8") if root_entry.exists() else ""
    if "index_v2.html" not in root_text or "window.location.search" not in root_text:
        fail("корінь GitHub Pages не перенаправляє в PWA зі збереженням query")
    else:
        ok("корінь GitHub Pages відкриває PWA і зберігає query")

    plans_start = shell.find('id="ov-plans"')
    plans_end = shell.find('id="ov-unsub"', plans_start)
    plans_markup = shell[plans_start:plans_end] if plans_start >= 0 and plans_end > plans_start else ""
    if 'onclick="closeOv()"' not in plans_markup or "closeOv();act(\\'paywall_remind_later\\')" not in shell:
        fail("paywall не можна безпечно закрити")
    else:
        ok("paywall має × і «Нагадати пізніше» закриває модальне вікно")


def test_visible_feature_map_and_role_workspaces():
    """Ключові функції мають прямі входи, а staff-панелі — role gate."""
    section("PWA — видимі функції, лексичний маршрут і рольові панелі")
    shell = SHELL.read_text(encoding="utf-8") if SHELL.exists() else ""
    markers = (
        'id="session-picker"', "function setSessionMinutes(minutes,quiet)",
        'id="home-chain-signal"', 'id="home-rank-signal"', 'id="home-online-signal"',
        'id="md-book"', "playerUrl.searchParams.set('minutes'",
        'id="ov-features"', "const FEATURE_REGISTRY=[", "renderFeatureRegistry()",
        'id="ov-chain"', "openProgressArea('chain')", "openProgressArea('rating')",
        'id="route-grammar"', 'id="route-lexical"', 'id="ov-lexical-topic"',
        "function openLexicalTopic(encoded)", "Побачила ", "Закріпила ",
        "openOv('ov-vocab')", "retellLastVideo()", "openDuelHistory()",
        'id="role-workspace"', "function verifiedWorkspaceRole(D,H)",
        "location.assign(u.toString())",
    )
    missing = [marker for marker in markers if marker not in shell]
    if missing:
        fail(f"карта можливостей/ролей неповна: {missing}")
    else:
        ok("ключові функції мають видимі входи, лексика — власний екран")

    for name in ("admin_analytics.html", "blogger.html", "strategy_dashboard.html"):
        text = (ROOT / name).read_text(encoding="utf-8")
        if not re.search(r'<script src="pwa\.js(?:\?[^"#]+)?"></script>', text):
            fail(f"{name}: PWA-сесія не підключена")
        else:
            ok(f"{name}: авторизована PWA-сесія підключена")
    vocab = (ROOT / "vocab.html").read_text(encoding="utf-8")
    vocab_markers = ("На повторення", "У процесі", "Закріплені", "Усі лексичні теми",
                     "function phraseState(p)", "speakchain-practice-phrase",
                     "Побачила ${seen", "Закріпила ${fixed", '<script src="pwa.js"></script>')
    missing_vocab = [marker for marker in vocab_markers if marker not in vocab]
    if missing_vocab:
        fail(f"словник не підключений до лексичного маршруту: {missing_vocab}")
    else:
        ok("словник має тематичні/SRS-фільтри й чотири стани засвоєння")
    raw_apps, _, _ = _extract_apps(shell)
    try:
        embedded_vocab = json.loads(raw_apps or "{}").get("ov-vocab", {})
        embedded_text = embedded_vocab.get("html", "") + embedded_vocab.get("js", "")
        if all(marker in embedded_text for marker in ("На повторення", "function phraseState(p)", "speakchain-practice-phrase")):
            ok("оновлений словник синхронізований у PWA-оболонку")
        else:
            fail("vocab.html оновлено, але вбудований ov-vocab залишився старим")
    except Exception as exc:
        fail(f"не вдалося перевірити вбудований словник: {exc}")
    if _has_node():
        scripts = re.findall(r"<script[^>]*>(.*?)</script>", vocab, re.S | re.I)
        if all(not script.strip() or _js_ok(script) for script in scripts):
            ok("vocab.html: JavaScript парситься")
        else:
            fail("vocab.html: JavaScript не парситься")


def test_blogger_panel_uses_shared_pwa_auth():
    """Direct browser access must reuse Google/PWA auth and load protected data."""
    section("Blogger panel — shared Google/PWA session")
    blogger = (ROOT / "blogger.html").read_text(encoding="utf-8")
    markers = (
        'src="pwa.js?v=20260805-auth1"', 'window.SC_PWA?.ready',
        "screen: 'blogger'", "pwa.js додає токен",
        "admin_view: adminView",
        "Авторитетна перевірка живе на", "initializeBloggerPanel()",
    )
    missing = [marker for marker in markers if marker not in blogger]
    if missing:
        fail("Панель блогера не підхоплює захищену PWA-сесію: " + ", ".join(missing))
    else:
        ok("Панель блогера повторно використовує Google/PWA-сесію та перевіряє роль")

    pwa = (ROOT / "pwa.js").read_text(encoding="utf-8")
    embedded_markers = (
        "function hasTrustedEmbeddedPayload()",
        "page === 'blogger.html'",
        "new URLSearchParams(location.search).has('d')",
        "source: 'telegram-payload'",
    )
    missing = [marker for marker in embedded_markers if marker not in pwa]
    if missing:
        fail("Telegram-payload панелі блогера помилково накриє форма входу: " + ", ".join(missing))
    else:
        ok("готова Telegram-панель блогера не запускає повторний браузерний вхід")

    admin = (ROOT / "admin_analytics.html").read_text(encoding="utf-8")
    if ("openBloggerPanel()" not in admin or "📣 Відкрити панель" not in admin
            or "url.searchParams.set('from', 'admin')" not in admin):
        fail("з кабінету адміністратора немає прямого входу в панель блогера")
    else:
        ok("адміністратор має прямий захищений вхід у панель блогера")

    selector_markers = (
        'id="blogger-panel-select"', 'function populateBloggerPanelSelect()',
        "url.searchParams.set('blogger', blogger)", "blogger_name: adminView ? selectedBlogger : ''",
        "if (D.admin_view)",
    )
    missing = [marker for marker in selector_markers if marker not in admin + blogger]
    if missing:
        fail("вибір окремої панелі блогера не завершений: " + ", ".join(missing))
    else:
        ok("адмін обирає конкретного блогера зі масштабованого списку")

    nav_markers = (
        "const MORE_NAV = [", "side-more-menu", "function openMoreTab(tab)",
        "['summary',  '🏠 Огляд']", "['system',   '⚙️ Система']",
    )
    missing = [marker for marker in nav_markers if marker not in admin]
    if missing:
        fail("адмін-меню не згортає дубльовані службові кнопки: " + ", ".join(missing))
    else:
        ok("адмін-меню показує 6 основних напрямів, решта зібрана в одному пункті «Ще»")


def test_error_srs_practice_is_reachable_and_records_results():
    """SRS має бути реальною вправою, а не невикликаною helper-функцією."""
    section("PWA — повний цикл опрацювання помилок")
    shell = SHELL.read_text(encoding="utf-8") if SHELL.exists() else ""
    markers = (
        "function openErrorPractice(items,index)",
        "function errorPracticeRepeat()",
        "function errorPracticeCheck()",
        "function practiceErrorWithChainy()",
        "function applyChainyErrorReviewResult(recap)",
        "window.SC_errorReview(pending.error_id,result.correct_in_own_speech===true)",
        "resource_kind:'error_srs'",
        "error_srs_result",
        "openErrorPractice(due,0)",
        "Лише результат розмови може зарахувати SRS-повторення",
    )
    missing = [marker for marker in markers if marker not in shell]
    if missing:
        fail(f"вправа SRS не зʼєднана з результатом: {missing}")
    else:
        ok("помилка проходить правильний варіант, власне речення, результат і SRS")


def test_session_minutes_change_the_actual_route():
    """5/15/30/60 хвилин мають змінювати дії, а не лише підпис героя."""
    section("PWA — маршрути за тривалістю сесії")
    shell = SHELL.read_text(encoding="utf-8") if SHELL.exists() else ""
    markers = (
        "if(SESSION_MINUTES===5&&!dp.speak)",
        "SESSION_MINUTES===15?",
        "SESSION_MINUTES===30?",
        "guidedSessionActionId('discover_vocab')",
        "guidedSessionActionId('discover_lexical')",
        "guidedSessionActionId('discover_match')",
        "function guidedSessionActionId(name)",
    )
    missing = [marker for marker in markers if marker not in shell]
    if missing:
        fail(f"тривалість не перебудовує маршрут: {missing}")
    else:
        ok("5/15/30/60 хвилин формують різні послідовності дій")


def test_own_video_is_visible_and_uses_the_shared_learning_loop():
    """Власне відео має бути видимим вибором і відкривати спільний плеєр."""
    section("PWA / Telegram — власне відео 15–60 хв")
    shell = SHELL.read_text(encoding="utf-8") if SHELL.exists() else ""
    player = (ROOT / "player.html").read_text(encoding="utf-8")
    markers = (
        "Працювати зі своїм відео",
        "встав YouTube-посилання · 15–60 хв",
        "function openOwnVideo()",
        "if(SESSION_MINUTES<15)",
        "setSessionMinutes(15)",
        "trackUx('own_video_open'",
        "{ic:'🔗',name:'Своє відео · 15–60 хв'",
    )
    player_markers = (
        'id="paste-url"',
        "function openPasted()",
        "function extractYtId(raw)",
        "type: 'speakchain-video-context'",
        "sessionSavedPhrases.slice(-5)",
    )
    missing = [marker for marker in markers if marker not in shell]
    missing += [marker for marker in player_markers if marker not in player]
    if missing:
        fail(f"власне відео не зʼєднане зі спільним навчальним циклом: {missing}")
    else:
        ok("власне відео доступне у PWA/Telegram і використовує плеєр, слова та Chainy")


def test_contextual_learning_cycle_ends_with_result_and_next_action():
    """Кожен навчальний вхід має повернути результат у свій маршрут."""
    section("PWA / Telegram — контекст → Chainy → результат")
    shell = SHELL.read_text(encoding="utf-8") if SHELL.exists() else ""
    markers = (
        "const LEARNING_CONTEXT_KEY=", "function setLearningContext(kind,label,extra)",
        "setLearningContext('lexical_topic',label", "setLearningContext('grammar_topic',t",
        "setLearningContext('vocabulary_phrase',phrase", "setLearningContext('error_srs',item.correct",
        "setLearningContext(event.data.resource_kind||'video'", "setLearningContext('book',title",
        "context?.kind==='lexical_topic'", "context?.kind==='grammar_topic'",
        "primary.dataset.next='guided_next'", "target==='lexical_progress'",
        "target==='grammar_progress'", "target==='guided_next'",
        "delete PAYLOAD['s-home'];delete PENDING['s-home']",
        "renderGuidedNavigation(TODAY_HOME||{})", "clearLearningContext();",
    )
    missing = [marker for marker in markers if marker not in shell]
    if missing:
        fail(f"контекстний цикл не завершений: {missing}")
    else:
        ok("слова, граматика, лексика, відео й SRS повертають результат і наступну дію")


def test_staff_and_learner_modes_are_two_way():
    """Службова роль не повинна втрачати учнівський режим або плодити вкладки."""
    section("PWA / Telegram — учнівський і службовий режими")
    shell = SHELL.read_text(encoding="utf-8") if SHELL.exists() else ""
    admin = (ROOT / "admin_analytics.html").read_text(encoding="utf-8")
    blogger = (ROOT / "blogger.html").read_text(encoding="utf-8")
    shell_markers = (
        "function openStaffWorkspace(page)", "location.assign(u.toString())",
        "workspace_mode_open", "function verifiedWorkspaceRole(D,H)",
        "role==='blogger'", "Панель адміністратора", "Панель блогера",
    )
    panel_markers = ("🎓 До навчання", "function openLearnerMode()", "new URL('index_v2.html',location.href)")
    missing = [m for m in shell_markers if m not in shell]
    missing += [f"admin:{m}" for m in panel_markers if m not in admin]
    missing += [f"blogger:{m}" for m in panel_markers if m not in blogger]
    if missing:
        fail(f"двосторонній перемикач ролей неповний: {missing}")
    else:
        ok("адміністратор і блогер перемикаються між службовою та учнівською панелями")


def test_guided_native_navigation():
    """Наступна дія адаптивна, пам'ятає стан і не закриває помилку за раз."""
    section("PWA — керована нативна навігація і SRS помилок")
    shell = SHELL.read_text(encoding="utf-8") if SHELL.exists() else ""
    markers = (
        'id="guided-card"', "const GUIDED_STATE_KEY=", "const ERROR_SRS_KEY=",
        "function guidedRecommendation(D)", "function runGuidedAction()",
        "function dismissGuidedAction()", "function renderGuidedNavigation(D)",
        "function mergeErrorSrs(items)", "function dueErrors(D)",
        "window.SC_errorReview=function", "item.success_uses>=3?'mastered':'reviewing'",
        "action:'error_srs_review'", "function openGuidedErrors()",
        "const errors=(recap.errors||recap.mistakes||d.recent_errors||d.errors||[])",
        "Опрацювати помилки", "Пропонуємо зараз, бо настав час повторення за SRS.",
    )
    missing = [marker for marker in markers if marker not in shell]
    if missing:
        fail(f"керована навігація/SRS неповні: {missing}")
    else:
        ok("навігація пам'ятає маршрут, дає одну наступну дію і повертає помилки за SRS")


def test_visible_lexical_streak_and_blogger_entry():
    """Три продуктові входи не залежать від неповної відповіді backend."""
    section("PWA — лексичні теми, Streak і фраза блогера")
    shell = SHELL.read_text(encoding="utf-8") if SHELL.exists() else ""
    markers = (
        'id="s-prog"', 'id="route-lexical"', "const LEXICAL_ROUTE_FALLBACK=",
        "function lexicalItems(D,level)", "function pgSetRoute(route)",
        'id="home-streak-signal"', "sc.querySelector('.l').textContent='Streak'",
        "const BLOGGER_ENTRY=", "function activateBloggerEntry(entry)",
        "blogger_phrase_repeat", "blogger_phrase_chainy",
        "function startBloggerPhraseChainy(entry)", "resource_kind:'blogger_phrase'",
        "function advanceBloggerEntryAfterPlayer()", "bloggerEntry.step==='context'",
        "bloggerEntry.step==='repeat'", "bloggerEntry.step==='chainy'",
        "updateBloggerEntry('complete')",
    )
    missing = [marker for marker in markers if marker not in shell]
    forbidden_home_markers = ('id="home-lexical-topics"', "function renderHomeLexical(D)")
    leaked_home = [marker for marker in forbidden_home_markers if marker in shell]
    fallback_levels = all(f" {level}:[[" in shell for level in ("A1", "A2", "B1", "B2", "C1", "C2"))
    if missing or leaked_home or not fallback_levels:
        fail(f"лексика/Streak/вхід блогера неповні: {missing}")
        if leaked_home:
            fail(f"лексичні теми помилково повернулися у «Сьогодні»: {leaked_home}")
        if not fallback_levels:
            fail("офлайн-лексичний маршрут не містить усіх рівнів A1–C2")
    else:
        ok("лексичні теми A1–C2 доступні офлайн лише у Прогресі; Streak і маршрут блогера збережені")


def test_desktop_shell_keeps_mobile_navigation_intact():
    """Desktop має власну композицію, але не замінює mobile/Telegram DOM."""
    section("PWA — повноцінна desktop-композиція")
    shell = SHELL.read_text(encoding="utf-8") if SHELL.exists() else ""
    markers = (
        "@media (min-width:900px)", "--desktop-nav:232px", "--desktop-rail:304px",
        "TG_DESKTOP_PLATFORMS", "document.documentElement.classList.add('telegram-desktop')",
        'class="desktop-rail"', 'aria-label="Швидка панель"',
        'id="desktop-progress-ring"', "const dailyDone=D?.nudge?.kind==='done'",
        "openLessonNow()", "openChainyNow()", "openOwnVideo()",
        '<div class="nav">', 'data-s="s-home"', 'data-s="s-listen"',
        'data-s="s-buddy"', 'data-s="s-social"', 'data-s="s-prog"',
    )
    missing = [marker for marker in markers if marker not in shell]
    if missing:
        fail(f"desktop-композиція або мобільна навігація неповні: {missing}")
    else:
        ok("desktop має ліве меню, широку робочу зону й праву панель; mobile-nav збережено")


def main():
    print("\033[1m" + "═" * 58)
    print("  SpeakChain — смоук-тести")
    print("═" * 58 + "\033[0m")

    test_files_present()
    test_python_syntax()
    test_imports_exist()
    test_helper_order()
    test_callbacks_have_handlers()
    test_no_type_the_command()
    test_timezone_exactly_once()
    test_promise_kept()
    test_shell_apps()
    test_pwa_identity_handoff()
    test_shell_router()
    test_analytics_dashboards()
    test_friends_stable_layers()
    test_profile_lottery_ux()
    test_production_assets_and_browser_chainy_auth()
    test_visible_feature_map_and_role_workspaces()
    test_blogger_panel_uses_shared_pwa_auth()
    test_error_srs_practice_is_reachable_and_records_results()
    test_session_minutes_change_the_actual_route()
    test_own_video_is_visible_and_uses_the_shared_learning_loop()
    test_contextual_learning_cycle_ends_with_result_and_next_action()
    test_staff_and_learner_modes_are_two_way()
    test_guided_native_navigation()
    test_visible_lexical_streak_and_blogger_entry()
    test_desktop_shell_keeps_mobile_navigation_intact()

    print("\n" + "═" * 58)
    if FAILS:
        print(f"\033[31m\033[1m  🔴 {len(FAILS)} ПОМИЛОК — НЕ ЛИЙ У ПРОД\033[0m\n")
        for f in FAILS:
            print(f"     • {f}")
        print()
        sys.exit(1)
    print(f"\033[32m\033[1m  ✅ {len(PASSES)} перевірок пройдено — можна лити\033[0m\n")
    sys.exit(0)


if __name__ == "__main__":
    main()
