from flask import Flask, render_template, request, redirect, flash, url_for, session
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from datetime import datetime, timedelta
import cx_Oracle
import os

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


# Модель пользователя для Flask-Login
class User(UserMixin):
    def __init__(self, id, email, kpo=None):
        self.id = id
        self.email = email
        self.kpo = kpo


# Загрузчик пользователя для Flask-Login
@login_manager.user_loader
def load_user(user_id):
    """Загружает пользователя из сессии"""
    user_email = session.get('user_email')
    user_kpo = session.get('user_kpo')
    if user_email:
        return User(int(user_id), user_email, user_kpo)
    return None


# ГЛАВНАЯ СТРАНИЦА
@app.route("/")
def index():
    return render_template('index.html')


# GET обработчик для страницы входа (для Flask-Login)
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
    print(f"   Логин (MAIL): {mail}")
    print(f"   Пароль: {password}")

    # Проверяем наличие данных
    if not mail or not password:
        flash('Заполните все поля', 'danger')
        return redirect('/')

    try:
        connection = get_oracle_connection()
        if not connection:
            flash('Ошибка подключения к базе данных', 'danger')
            return redirect('/')

        cursor = connection.cursor()

        # 1. Ищем пользователя по MAIL
        cursor.execute("""
            SELECT PERS_AUT_ID, MAIL, PASSWORD, KSOST, PERS_ROOM_ID 
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

        user_id, user_mail, user_password, ksost, pers_room_id = result

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

            # Получаем KPO пользователя из PERS_ROOM
            cursor.execute("""
                SELECT KPO FROM PERS_ROOM 
                WHERE PERS_ROOM_ID = :pers_room_id
            """, pers_room_id=pers_room_id)

            kpo_result = cursor.fetchone()
            kpo = kpo_result[0] if kpo_result else None

            cursor.close()
            connection.close()

            # Сохраняем дополнительные данные в сессии
            session['user_email'] = user_mail
            session['user_kpo'] = kpo

            # Создаем объект User для Flask-Login
            user = User(user_id, user_mail, kpo)

            # Логиним пользователя
            login_user(user)

            flash('Вы успешно вошли!', 'success')
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


# Функция для получения организации пользователя
def get_current_organization():
    """Получаем организацию текущего пользователя из Oracle"""
    if current_user.is_authenticated and current_user.kpo:
        try:
            connection = get_oracle_connection()
            if connection:
                cursor = connection.cursor()
                cursor.execute("""
                    SELECT NPO, INN, ADRES 
                    FROM KL_PRED 
                    WHERE KPO = :kpo
                """, kpo=current_user.kpo)

                result = cursor.fetchone()
                cursor.close()
                connection.close()

                if result:
                    npo, inn, adres = result
                    return {
                        'npo': npo,  # А1 - NPO из KL_PRED
                        'inn': inn,  # А2 - INN из KL_PRED
                        'adres': adres  # А3 - ADRES из KL_PRED
                    }
        except cx_Oracle.Error as e:
            print(f"Ошибка получения организации: {e}")
    return None


# Маршрут profile
@app.route("/profile")
@login_required
def profile():
    organization = get_current_organization()
    if not organization:
        flash('Организация не найдена', 'danger')
        return redirect('/')
    return render_template('profile.html', organization=organization)


# Маршрут contracts с возможностью показа всех договоров без фильтрации по дате
@app.route("/contracts", methods=['GET'])
@login_required
def contracts():
    if not current_user.kpo:
        flash('Организация не найдена', 'danger')
        return redirect('/profile')

    try:
        connection = get_oracle_connection()
        if not connection:
            flash('Ошибка подключения к базе данных', 'danger')
            return redirect('/profile')

        cursor = connection.cursor()

        # Получаем параметры запроса
        start_date_str = request.args.get('start_date')
        end_date_str = request.args.get('end_date')
        show_all = request.args.get('show_all') == 'true'

        # SQL запрос - разный в зависимости от режима
        if show_all:
            print(f"   📋 Показываем ВСЕ договора для KPO={current_user.kpo} (без фильтра по дате)")
            # Запрос БЕЗ фильтрации по дате
            sql_query = """
                SELECT 
                    rd.NUM_DOG,
                    rd.DATA_REG,
                    rd.DAT_BEG_DOG,
                    rd.DAT_END_DOG,
                    kd.NAIM_DOG,
                    ks.NAME
                FROM REG_DOGOVOR rd
                LEFT JOIN KL_DOGOVOR kd ON rd.KOD_VID_DOG = kd.KOD_VID_DOG
                LEFT JOIN KL_SORT_PROD ks ON rd.PREDM_DOG = ks.KOD_UKR_SORT
                WHERE rd.KPO = :kpo 
                AND SUBSTR(rd.NUM_DOG, -1) NOT IN ('Т', 'И')
                ORDER BY rd.DATA_REG DESC
            """
            params = {'kpo': current_user.kpo}

            # Для отображения берем крайние даты из БД
            cursor.execute("""
                SELECT MIN(DATA_REG), MAX(DATA_REG) 
                FROM REG_DOGOVOR 
                WHERE KPO = :kpo
            """, kpo=current_user.kpo)
            min_max_dates = cursor.fetchone()

            if min_max_dates and min_max_dates[0] and min_max_dates[1]:
                start_date = min_max_dates[0]
                end_date = min_max_dates[1]
            else:
                start_date = datetime.now() - timedelta(days=365)
                end_date = datetime.now()

        else:
            # Фильтрация по датам
            if start_date_str and end_date_str:
                try:
                    start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
                    end_date = datetime.strptime(end_date_str, '%Y-%m-%d')
                except ValueError:
                    flash('Неверный формат даты', 'danger')
                    start_date = datetime.now() - timedelta(days=365)
                    end_date = datetime.now()
            else:
                end_date = datetime.now()
                start_date = end_date - timedelta(days=365)

            # Запрос с фильтрацией по дате
            sql_query = """
                SELECT 
                    rd.NUM_DOG,
                    rd.DATA_REG,
                    rd.DAT_BEG_DOG,
                    rd.DAT_END_DOG,
                    kd.NAIM_DOG,
                    ks.NAME
                FROM REG_DOGOVOR rd
                LEFT JOIN KL_DOGOVOR kd ON rd.KOD_VID_DOG = kd.KOD_VID_DOG
                LEFT JOIN KL_SORT_PROD ks ON rd.PREDM_DOG = ks.KOD_UKR_SORT
                WHERE rd.KPO = :kpo 
                AND rd.DATA_REG BETWEEN :start_date AND :end_date
                AND SUBSTR(rd.NUM_DOG, -1) NOT IN ('Т', 'И')
                ORDER BY rd.DATA_REG DESC
            """
            params = {'kpo': current_user.kpo, 'start_date': start_date, 'end_date': end_date}

        # Выполняем запрос
        print(f"   SQL запрос: {sql_query[:100]}...")
        cursor.execute(sql_query, params)
        contracts_data = cursor.fetchall()

        # Получаем общее количество договоров (для информации)
        cursor.execute("""
            SELECT COUNT(*) 
            FROM REG_DOGOVOR 
            WHERE KPO = :kpo 
            AND SUBSTR(NUM_DOG, -1) NOT IN ('Т', 'И')
        """, kpo=current_user.kpo)
        total_contracts = cursor.fetchone()[0]

        cursor.close()
        connection.close()

        # Обрабатываем данные
        contracts_list = []
        for contract in contracts_data:
            num_dog, data_reg, dat_beg_dog, dat_end_dog, naim_dog, name = contract

            data_reg_str = data_reg.strftime('%d.%m.%Y') if data_reg else ''
            dat_beg_str = dat_beg_dog.strftime('%d.%m.%Y') if dat_beg_dog else ''
            dat_end_str = dat_end_dog.strftime('%d.%m.%Y') if dat_end_dog else ''
            period_str = f"{dat_beg_str} – {dat_end_str}" if dat_beg_str and dat_end_str else ''

            contracts_list.append({
                'num_dog': num_dog,
                'data_reg': data_reg_str,
                'period': period_str,
                'vid_dog': naim_dog or '',
                'predmet': name or ''
            })

        # Подготавливаем данные для отображения
        if show_all:
            date_display = {
                'start_date': start_date.strftime('%d.%m.%Y') if hasattr(start_date, 'strftime') else '—',
                'end_date': end_date.strftime('%d.%m.%Y') if hasattr(end_date, 'strftime') else '—',
                'start_date_input': start_date.strftime('%Y-%m-%d') if hasattr(start_date, 'strftime') else '',
                'end_date_input': end_date.strftime('%Y-%m-%d') if hasattr(end_date, 'strftime') else '',
                'show_all': True
            }
        else:
            date_display = {
                'start_date': start_date.strftime('%d.%m.%Y'),
                'end_date': end_date.strftime('%d.%m.%Y'),
                'start_date_input': start_date.strftime('%Y-%m-%d'),
                'end_date_input': end_date.strftime('%Y-%m-%d'),
                'show_all': False
            }

        return render_template('contracts.html',
                               contracts=contracts_list,
                               dates=date_display,
                               kpo=current_user.kpo,
                               total_contracts=total_contracts,
                               filtered_count=len(contracts_list))

    except cx_Oracle.Error as e:
        print(f"Ошибка получения договоров: {e}")
        flash('Ошибка получения данных', 'danger')

    # Возвращаем пустой список если ошибка
    return render_template('contracts.html', contracts=[], dates={
        'start_date': (datetime.now() - timedelta(days=365)).strftime('%d.%m.%Y'),
        'end_date': datetime.now().strftime('%d.%m.%Y'),
        'start_date_input': (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d'),
        'end_date_input': datetime.now().strftime('%Y-%m-%d'),
        'show_all': False
    }, kpo=current_user.kpo, total_contracts=0, filtered_count=0)


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

    # Проверяем подключение
    print("Проверка подключения к Oracle...")
    connection = get_oracle_connection()
    if connection:
        print("✅ Подключение к Oracle успешно")

        # Быстрая проверка данных
        try:
            cursor = connection.cursor()
            cursor.execute("SELECT USER FROM DUAL")
            user = cursor.fetchone()[0]
            print(f"Пользователь Oracle: {user}")

            cursor.execute("SELECT COUNT(*) FROM PERS_ROOM_AUT")
            count = cursor.fetchone()[0]
            print(f"Записей в PERS_ROOM_AUT: {count}")

            cursor.execute("SELECT COUNT(*) FROM PERS_ROOM")
            count_pr = cursor.fetchone()[0]
            print(f"Записей в PERS_ROOM: {count_pr}")

            cursor.execute("SELECT COUNT(*) FROM KL_PRED")
            count_kp = cursor.fetchone()[0]
            print(f"Записей в KL_PRED: {count_kp}")

            cursor.close()
        except Exception as e:
            print(f"Ошибка проверки: {e}")

        connection.close()
    else:
        print("❌ Не удалось подключиться к Oracle")

    app.run(debug=True, port=5000)



