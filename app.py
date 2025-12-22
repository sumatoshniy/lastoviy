from flask import Flask, render_template, request, redirect, flash, url_for, session
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
import cx_Oracle

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret123'

# Инициализация Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login_page'

# Конфигурация подключения к Oracle
ORACLE_CONFIG = {
    'user': 'S100058',
    'password': 'S100058',
    'dsn': '10.4.30.43:1521/test'
}


def get_oracle_connection():
    """Создает подключение к Oracle"""
    try:
        connection = cx_Oracle.connect(**ORACLE_CONFIG)
        return connection
    except cx_Oracle.Error as e:
        print(f"Ошибка подключения к Oracle: {e}")
        return None


# Модель пользователя
class User(UserMixin):
    def __init__(self, id, email):
        self.id = id
        self.email = email


# Загрузчик пользователя
@login_manager.user_loader
def load_user(user_id):
    """Загружает пользователя из сессии"""
    user_email = session.get('user_email')
    if user_email:
        return User(int(user_id), user_email)
    return None


# ГЛАВНАЯ СТРАНИЦА с формой входа
@app.route("/")
def index():
    return render_template('index.html')


# GET обработчик для страницы входа
@app.route("/login", methods=['GET'])
def login_page():
    return redirect('/')


# POST обработчик для входа
@app.route("/login", methods=['POST'])
def login():
    # Получаем данные из формы
    mail = request.form.get('username', '').strip()
    password = request.form.get('password', '').strip()

    print(f"\n🔐 ПОПЫТКА АВТОРИЗАЦИИ:")
    print(f"   Логин: {mail}")
    print(f"   Пароль: {password}")

    # Проверяем наличие данных
    if not mail or not password:
        flash('Заполните все поля', 'danger')
        return redirect('/')

    try:
        # Подключаемся к Oracle
        connection = get_oracle_connection()
        if not connection:
            flash('Ошибка подключения к базе данных', 'danger')
            return redirect('/')

        cursor = connection.cursor()

        # Запрос к таблице PERS_ROOM_AUT
        cursor.execute("""
            SELECT PERS_AUT_ID, MAIL, PASSWORD, KSOST 
            FROM PERS_ROOM_AUT 
            WHERE MAIL = :mail
        """, mail=mail)

        result = cursor.fetchone()

        # 1. Если запись отсутствует
        if not result:
            print("   ❌ Пользователь не зарегистрирован")
            cursor.close()
            connection.close()
            flash('Пользователь не зарегистрирован', 'danger')
            return redirect('/')

        user_id, user_mail, user_password, ksost = result

        print(f"   Данные из БД:")
        print(f"     ID: {user_id}")
        print(f"     MAIL: {user_mail}")
        print(f"     PASSWORD: {user_password}")
        print(f"     KSOST: {ksost}")

        # 2. Если пользователь заблокирован (KSOST=2)
        if ksost == 2:
            print("   ⚠️  Пользователь заблокирован")
            cursor.close()
            connection.close()
            flash('Пользователь заблокирован, обратитесь к менеджеру', 'warning')
            return redirect('/')

        # 3. Проверяем пароль (KSOST=1 и правильный пароль)
        if ksost == 1 and user_password == password:
            print("   ✅ Авторизация успешна")

            cursor.close()
            connection.close()

            # Сохраняем email в сессии
            session['user_email'] = user_mail

            # Логиним пользователя
            user = User(user_id, user_mail)
            login_user(user)

            flash('Вы успешно вошли в систему!', 'success')
            return redirect('/profile')

        # 4. Неверный пароль
        print("   ❌ Неверный пароль")
        cursor.close()
        connection.close()
        flash('ОШИБКА! Неверный пароль', 'danger')
        return redirect('/')

    except cx_Oracle.Error as e:
        print(f"Ошибка базы данных: {e}")
        flash('Ошибка базы данных', 'danger')
        return redirect('/')


# Профиль пользователя
@app.route("/profile")
@login_required
def profile():
    # Получаем данные организации из Oracle
    organization_data = None

    try:
        connection = get_oracle_connection()
        if connection:
            cursor = connection.cursor()

            # Получаем KPO пользователя из PERS_ROOM
            cursor.execute("""
                SELECT pr.KPO 
                FROM PERS_ROOM pr
                JOIN PERS_ROOM_AUT pra ON pr.PERS_ROOM_ID = pra.PERS_ROOM_ID
                WHERE pra.MAIL = :mail
            """, mail=current_user.email)

            kpo_result = cursor.fetchone()

            if kpo_result:
                kpo = kpo_result[0]

                # Получаем данные организации
                cursor.execute("""
                    SELECT NPO, INN, ADRES 
                    FROM KL_PRED 
                    WHERE KPO = :kpo
                """, kpo=kpo)

                org_result = cursor.fetchone()
                if org_result:
                    organization_data = {
                        'npo': org_result[0],
                        'inn': org_result[1],
                        'adres': org_result[2]
                    }

            cursor.close()
            connection.close()
    except:
        pass

    # Если не нашли в БД, используем тестовые данные
    if not organization_data:
        organization_data = {
            'npo': 'Тестовая организация',
            'inn': '1234567890',
            'adres': 'Тестовый адрес'
        }

    return render_template('profile.html', organization=organization_data)


# Договора
@app.route("/contracts")
@login_required
def contracts():
    contracts_data = []

    try:
        connection = get_oracle_connection()
        if connection:
            cursor = connection.cursor()

            # Получаем KPO пользователя
            cursor.execute("""
                SELECT pr.KPO 
                FROM PERS_ROOM pr
                JOIN PERS_ROOM_AUT pra ON pr.PERS_ROOM_ID = pra.PERS_ROOM_ID
                WHERE pra.MAIL = :mail
            """, mail=current_user.email)

            kpo_result = cursor.fetchone()

            if kpo_result:
                kpo = kpo_result[0]

                # Получаем договора за последний год
                cursor.execute("""
                    SELECT NUM_DOG, DATA_REG 
                    FROM REG_DOGOVOR 
                    WHERE KPO = :kpo 
                    AND DATA_REG >= ADD_MONTHS(SYSDATE, -12)
                    ORDER BY DATA_REG DESC
                """, kpo=kpo)

                contracts = cursor.fetchall()
                for contract in contracts:
                    contracts_data.append({
                        'num_dog': contract[0],
                        'data_reg': contract[1].strftime('%d.%m.%Y') if contract[1] else ''
                    })

            cursor.close()
            connection.close()
    except:
        pass

    return render_template('contracts.html', contracts=contracts_data)


# Выход
@app.route("/logout")
@login_required
def logout():
    session.clear()
    logout_user()
    flash('Вы вышли из системы', 'info')
    return redirect('/')


# Страница "О нас"
@app.route("/about")
def about():
    return render_template('about.html')


if __name__ == '__main__':
    print("=" * 50)
    print("Запуск веб-приложения 'Личный кабинет контрагента'")
    print("=" * 50)

    # Проверка подключения к Oracle
    print("Проверка подключения к Oracle...")
    connection = get_oracle_connection()
    if connection:
        print("✅ Подключение к Oracle успешно")
        connection.close()
    else:
        print("❌ Не удалось подключиться к Oracle")

    app.run(debug=True, port=5000)