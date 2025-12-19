from flask import Flask, render_template, request, redirect, flash, url_for, session
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from datetime import datetime, timedelta
import os
import cx_Oracle
import traceback

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret123'

# Настройки подключения к Oracle
ORACLE_USER = 'S100058'
ORACLE_PASSWORD = 'S100058'
ORACLE_HOST = '10.4.30.43'
ORACLE_PORT = '1521'
ORACLE_SERVICE = 'test'

# Создаем DSN
DSN = cx_Oracle.makedsn(ORACLE_HOST, ORACLE_PORT, service_name=ORACLE_SERVICE)

# Инициализация Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'


# Класс для пользователя
class User(UserMixin):
    def __init__(self, mail, kpo):
        self.id = mail  # Используем email как ID
        self.email = mail
        self.username = mail
        self.kpo = kpo


# Загрузчик пользователя
@login_manager.user_loader
def load_user(user_id):
    if 'user_id' in session:
        return User(
            mail=session['user_mail'],
            kpo=session.get('user_kpo')
        )
    return None


# Функции для работы с БД через cx_Oracle
class DatabaseService:
    @staticmethod
    def get_connection():
        """Создает соединение с Oracle"""
        try:
            connection = cx_Oracle.connect(
                user=ORACLE_USER,
                password=ORACLE_PASSWORD,
                dsn=DSN,
                encoding="UTF-8"
            )
            return connection
        except cx_Oracle.Error as e:
            print(f"Ошибка подключения к Oracle: {e}")
            raise

    @staticmethod
    def check_user_auth(mail, password):
        """
        Проверка авторизации согласно ТЗ
        Возвращает: (успех, данные или сообщение об ошибке)
        """
        connection = None
        cursor = None
        try:
            connection = DatabaseService.get_connection()
            cursor = connection.cursor()

            # 1. Ищем пользователя по MAIL в т.PERS_ROOM_AUT
            query = """
                SELECT MAIL, PASSWORD, KSOST, KPO 
                FROM PERS_ROOM_AUT 
                WHERE MAIL = :mail
            """

            cursor.execute(query, mail=mail)
            result = cursor.fetchone()

            if not result:
                return False, "Пользователь не зарегистрирован"

            # Распаковываем результат
            db_mail, db_password, ksost, kpo = result

            # 2. Проверяем статус KSOST
            if ksost == 2:
                return False, "Пользователь заблокирован, обратитесь к менеджеру"

            # 3. Проверяем пароль (KSOST=1 и правильный пароль)
            if ksost == 1 and db_password == password:
                user_data = {
                    'mail': db_mail,
                    'kpo': kpo,
                    'ksost': ksost
                }
                return True, user_data

            # 4. Неверный пароль
            return False, "ОШИБКА! Неверный пароль"

        except cx_Oracle.Error as e:
            print(f"Ошибка Oracle при авторизации: {e}")
            error_message = str(e)
            return False, f"Ошибка базы данных: {error_message}"
        finally:
            if cursor:
                cursor.close()
            if connection:
                connection.close()

    @staticmethod
    def get_organization_info(kpo):
        """Получаем информацию об организации по KPO"""
        connection = None
        cursor = None
        try:
            connection = DatabaseService.get_connection()
            cursor = connection.cursor()

            # Запрос по ТЗ: A1, A2, A3 из т.KL_PRED
            query = """
                SELECT NPO, INN, ADRESS as ADDRESS 
                FROM KL_PRED 
                WHERE KPO = :kpo
            """

            cursor.execute(query, kpo=kpo)
            result = cursor.fetchone()

            if result:
                npo, inn, address = result
                return {
                    'npo': npo,
                    'inn': inn,
                    'address': address
                }
            return None

        except cx_Oracle.Error as e:
            print(f"Ошибка Oracle при получении организации: {e}")
            return None
        finally:
            if cursor:
                cursor.close()
            if connection:
                connection.close()

    @staticmethod
    def get_contracts(kpo, start_date, end_date):
        """
        Получаем договора по организации за период
        Согласно ТЗ: Б1-Б5
        """
        connection = None
        cursor = None
        try:
            connection = DatabaseService.get_connection()
            cursor = connection.cursor()

            # Основной запрос согласно ТЗ
            query = """
                SELECT 
                    rd.NUM_DOG as NUM_DOG,
                    TO_CHAR(rd.DATA_REG, 'dd.mm.yyyy') as DATA_REG,
                    TO_CHAR(rd.DAT_BEG_DOG, 'dd.mm.yyyy') || '--' || TO_CHAR(rd.DAT_END_DOG, 'dd.mm.yyyy') as PERIOD,
                    kd.NAIM_DOG as VID_DOG,
                    ksp.NAME as PREDMET
                FROM REG_DOGOVOR rd
                LEFT JOIN KL_DOGOVOR kd ON rd.KOD_VID_DOG = kd.KOD_VID_DOG
                LEFT JOIN KL_SORT_PROD ksp ON rd.PREDM_DOG = ksp.KOD_UKR_SORT
                WHERE rd.KPO = :kpo
                AND rd.DATA_REG BETWEEN TO_DATE(:start_date, 'YYYY-MM-DD') AND TO_DATE(:end_date, 'YYYY-MM-DD')
                AND SUBSTR(rd.NUM_DOG, -1) NOT IN ('Т', 'И')
                ORDER BY rd.DATA_REG DESC
            """

            cursor.execute(query,
                           kpo=kpo,
                           start_date=start_date.strftime('%Y-%m-%d'),
                           end_date=end_date.strftime('%Y-%m-%d'))

            results = cursor.fetchall()

            contracts = []
            for row in results:
                contracts.append({
                    'num_dog': row[0],
                    'data_reg': row[1],
                    'period': row[2],
                    'vid_dog': row[3] if row[3] else '',
                    'predmet': row[4] if row[4] else ''
                })

            return contracts

        except cx_Oracle.Error as e:
            print(f"Ошибка Oracle при получении договоров: {e}")
            print(traceback.format_exc())
            return []
        finally:
            if cursor:
                cursor.close()
            if connection:
                connection.close()

    @staticmethod
    def test_connection():
        """Тестовый запрос для проверки подключения"""
        connection = None
        cursor = None
        try:
            connection = DatabaseService.get_connection()
            cursor = connection.cursor()
            cursor.execute("SELECT 1 FROM DUAL")
            result = cursor.fetchone()
            return True, f"Подключение успешно! Результат: {result[0]}"
        except cx_Oracle.Error as e:
            return False, f"Ошибка подключения: {str(e)}"
        finally:
            if cursor:
                cursor.close()
            if connection:
                connection.close()


# Маршруты
@app.route("/login", methods=['POST'])
def login():
    mail = request.form.get('username')
    password = request.form.get('password')

    print(f"\n🔐 ПОПЫТКА АВТОРИЗАЦИИ:")
    print(f"   Логин (MAIL): {mail}")
    print(f"   Пароль: {password}")

    if not mail or not password:
        flash('Заполните все поля', 'danger')
        return redirect('/')

    success, result = DatabaseService.check_user_auth(mail, password)

    if success:
        user_data = result

        user = User(
            mail=user_data['mail'],
            kpo=user_data['kpo']
        )

        # Сохраняем данные в сессии
        session['user_id'] = user.id
        session['user_mail'] = user_data['mail']
        session['user_kpo'] = user_data['kpo']

        # Логиним пользователя
        login_user(user, remember=True)

        print(f"   ✅ Авторизация успешна для пользователя: {user_data['mail']}")
        flash('Вы успешно вошли!', 'success')
        return redirect('/profile')
    else:
        error_message = result
        print(f"   ❌ Ошибка: {error_message}")
        flash(error_message, 'danger')
        return redirect('/')


def get_current_organization():
    if current_user.is_authenticated:
        kpo = session.get('user_kpo')
        if kpo:
            return DatabaseService.get_organization_info(kpo)
    return None


@app.route("/profile")
@login_required
def profile():
    organization = get_current_organization()
    if not organization:
        flash('Организация не найдена', 'danger')
        return redirect('/')
    return render_template('profile.html', organization=organization)


@app.route("/contracts", methods=['GET'])
@login_required
def contracts():
    user_kpo = session.get('user_kpo')

    if not user_kpo:
        flash('Пользователь не привязан к организации', 'danger')
        return redirect('/profile')

    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')
    today = datetime.now().date()

    if start_date_str and end_date_str:
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()

            if start_date > end_date:
                flash('Начальная дата не может быть позже конечной', 'warning')
                start_date, end_date = end_date, start_date
        except ValueError:
            flash('Неверный формат даты', 'danger')
            end_date = today
            start_date = end_date - timedelta(days=365)
    else:
        end_date = today
        start_date = end_date - timedelta(days=365)

    # Получаем договора
    contracts_list = DatabaseService.get_contracts(
        kpo=user_kpo,
        start_date=start_date,
        end_date=end_date
    )

    date_display = {
        'start_date': start_date.strftime('%d.%m.%Y'),
        'end_date': end_date.strftime('%d.%m.%Y'),
        'start_date_input': start_date.strftime('%Y-%m-%d'),
        'end_date_input': end_date.strftime('%Y-%m-%d')
    }

    return render_template('contracts.html',
                           contracts=contracts_list,
                           dates=date_display)


@app.route("/")
def index():
    return render_template('index.html')


@app.route("/logout")
@login_required
def logout():
    session.clear()
    logout_user()
    flash('Вы вышли из системы', 'info')
    return redirect('/')


@app.route("/about")
def about():
    return render_template('about.html')


@app.route("/test-db")
def test_db():
    success, message = DatabaseService.test_connection()
    if success:
        return f"<h3>✅ {message}</h3>"
    else:
        return f"<h3>❌ {message}</h3>"


if __name__ == '__main__':
    print("=" * 60)
    print("Запуск Личного кабинета контрагента АО БМК")
    print("=" * 60)
    print(f"Подключение к Oracle:")
    print(f"  Пользователь: {ORACLE_USER}")
    print(f"  Хост: {ORACLE_HOST}:{ORACLE_PORT}")
    print(f"  Сервис: {ORACLE_SERVICE}")
    print("=" * 60)

    # Тестируем подключение при запуске
    print("🔍 Тестируем подключение к базе данных...")
    success, message = DatabaseService.test_connection()
    if success:
        print(f"✅ {message}")
    else:
        print(f"⚠️  {message}")
        print("Приложение запустится, но возможны ошибки при работе с БД")

    app.run(debug=True, port=5000, host='0.0.0.0')