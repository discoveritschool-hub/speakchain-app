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
    shell_js = src[src.rfind("<script>") + 8: src.rfind("</script>")]
    if _js_ok(shell_js):
        ok("JS оболонки парситься")
    else:
        fail("JS оболонки зламано")


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
    shell_js = src[src.rfind("<script>") + 8: src.rfind("</script>")]

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
    for ov in re.findall(r"'(ov-[a-z]+)'", ovs.group(1) if ovs else ""):
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
    test_shell_router()

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
