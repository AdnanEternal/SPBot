import subprocess
import sys
from pathlib import Path

def ensure_dependencies():
    """چک و نصب وابستگی‌ها (فقط یک بار)"""
    requirements_path = Path("requirements.txt")
    
    if not requirements_path.exists():
        print("❌ requirements.txt پیدا نشد!")
        sys.exit(1)
    
    # پکیج‌های مورد نیاز (بدون کامنت و خالی)
    with open(requirements_path) as f:
        required = {line.strip() for line in f if line.strip() and not line.startswith("#")}
    
    # چک پکیج‌های نصب‌شده
    installed = subprocess.check_output([sys.executable, "-m", "pip", "list", "--format=freeze"]).decode()
    installed_packages = {line.split("==")[0] for line in installed.splitlines()}
    
    missing = required - installed_packages
    if missing:
        print(f"🔧 نصب {len(missing)} وابستگی نصبه: {sorted(missing)}")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", str(requirements_path)])
            print("✅ همه وابستگی‌ها با موفقیت نصب شدن!")
        except subprocess.CalledProcessError:
            print("❌ نصب وابستگی‌ها با خطا مواجه شد!")
            sys.exit(1)
    else:
        print("✅ همه وابستگی‌ها قبلاً نصب بودن.")

# ===================== فقط برای اجرای مستقیم =====================
if __name__ == "__main__":
    ensure_dependencies()
