import cx_Oracle
from flask import Flask, render_template, request, redirect, url_for, session, flash
from functools import wraps
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'your-secret-key-change-this-in-production'

print("=" * 70)
print("ЛИЧНЫЙ КАБИНЕТ КОНТРАГЕНТА АО БМК - ORACLE")
print("=" * 70)


# ===== ORACLE CONNECTION =====
def get_db_connection():
    """Подключение к Oracle"""
    try:
        conn = cx_Oracle.connect('S100058/S100058@10.4.30.43:1521/test')
        print(f"✅ Подключение к Oracle: УСПЕШНО")
        return conn
    except Exception as e:
        print(f"❌ Ошибка подключения к Oracle: {e}")
        return None


def login_required(f):
    """Декоратор для проверки авторизации"""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Пожалуйста, войдите в систему', 'danger')
            return redirect(url_for('index'))
        return f(*args, **kwargs)

    return decorated_function


# ===== МАРШРУТЫ =====

@app.route('/')
def index():
    """Главная страница"""
    return render_template('index.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    """Вход в систему"""
    if request.method == 'GET':
        return redirect(url_for('index'))

    # Обработка POST запроса
    email = request.form.get('username')
    password = request.form.get('password')

    if not email or not password:
        flash('Введите email и пароль', 'danger')
        return redirect(url_for('index'))

    conn = get_db_connection()
    if not conn:
        flash('Ошибка подключения к базе данных', 'danger')
        return redirect(url_for('index'))

    try:
        cursor = conn.cursor()

        # Запрос для авторизации с получением данных организации
        query = """
        SELECT 
            pra.PERS_AUT_ID, 
            pra.MAIL,
            pra.PERS_ROOM_ID,
            pr.KPO,
            NVL(kp.NPO, 'Не указано') as org_name,
            NVL(kp.INN, 'Не указан') as org_inn,
            NVL(kp.ADRES, 'Не указан') as org_address
        FROM PERS_ROOM_AUT pra
        JOIN PERS_ROOM pr ON pra.PERS_ROOM_ID = pr.PERS_ROOM_ID
        LEFT JOIN KL_PRED kp ON pr.KPO = kp.KPO
        WHERE UPPER(pra.MAIL) = UPPER(:email)
          AND pra.PASSWORD = :password
          AND pra.KSOST = 0
        """

        cursor.execute(query, email=email, password=password)
        user = cursor.fetchone()

        if user:
            # Сохраняем все данные в сессии
            session['user_id'] = user[0]
            session['email'] = user[1]
            session['pers_room_id'] = user[2]
            session['kpo'] = user[3]
            session['org_name'] = user[4]
            session['org_inn'] = user[5]
            session['org_address'] = user[6]

            flash('Вход выполнен успешно!', 'success')
            print(f"✅ Пользователь вошел: {email}")
        else:
            flash('Неверный email или пароль', 'danger')
            print(f"❌ Неудачный вход: {email}")

        cursor.close()
        conn.close()

    except Exception as e:
        flash(f'Ошибка базы данных: {e}', 'danger')
        print(f"❌ Ошибка БД: {e}")

    return redirect(url_for('index'))


@app.route('/profile')
@login_required
def profile():
    """Личный кабинет - информация об организации"""
    conn = get_db_connection()
    organization = None

    if conn:
        try:
            cursor = conn.cursor()

            # Получаем полную информацию об организации
            query = """
            SELECT 
                kp.NPO,
                kp.INN,
                kp.ADRES,
                kp.KPO,
                (SELECT COUNT(*) FROM REG_DOGOVOR WHERE KPO = kp.KPO) as contract_count
            FROM KL_PRED kp
            WHERE kp.KPO = :kpo
            """

            cursor.execute(query, kpo=session.get('kpo'))
            org_data = cursor.fetchone()

            if org_data:
                organization = {
                    'npo': org_data[0],
                    'inn': org_data[1],
                    'address': org_data[2],
                    'kpo': org_data[3],
                    'contract_count': org_data[4]
                }

            cursor.close()
            conn.close()

        except Exception as e:
            print(f"Ошибка при получении данных организации: {e}")

    # Если не нашли в KL_PRED, используем данные из сессии
    if not organization:
        organization = {
            'npo': session.get('org_name', 'Не указано'),
            'inn': session.get('org_inn', 'Не указан'),
            'address': session.get('org_address', 'Не указан'),
            'kpo': session.get('kpo', 'Не указан'),
            'contract_count': 0
        }

    return render_template('profile.html', organization=organization)


@app.route('/contracts')
@login_required
def contracts():
    """Список договоров с фильтрацией по дате"""
    conn = get_db_connection()
    contracts_list = []

    # Получаем параметры фильтрации
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')

    # Форматируем даты для отображения
    display_dates = {
        'start_date': start_date if start_date else 'не указана',
        'end_date': end_date if end_date else 'не указана'
    }

    if conn:
        try:
            cursor = conn.cursor()

            # Базовый запрос
            query = """
            SELECT 
                PREDM_DOG as subject,
                KPO as org_code
            FROM REG_DOGOVOR 
            WHERE KPO = :kpo
            """
            params = {'kpo': session.get('kpo')}

            # Добавляем фильтрацию по дате если указана
            # Примечание: В вашей таблице REG_DOGOVOR может не быть поля с датой
            # Если нужно фильтровать по дате, уточните структуру таблицы

            query += " ORDER BY PREDM_DOG"

            cursor.execute(query, params)

            for row in cursor:
                contracts_list.append({
                    'subject': row[0],
                    'org_code': row[1]
                })

            cursor.close()
            conn.close()

        except Exception as e:
            flash(f'Ошибка при получении договоров: {e}', 'danger')
            print(f"Ошибка договоров: {e}")

    return render_template('contracts.html',
                           contracts=contracts_list,
                           dates=display_dates)


@app.route('/contracts/<int:contract_id>')
@login_required
def contract_detail(contract_id):
    """Детальная информация о договоре"""
    # Если нужна детальная страница договора
    return f"Детали договора #{contract_id}"


@app.route('/organizations')
@login_required
def organizations():
    """Список всех организаций"""
    conn = get_db_connection()
    organizations_list = []

    if conn:
        try:
            cursor = conn.cursor()

            # Получаем все организации
            query = """
            SELECT 
                NPO as name,
                KPO as code,
                INN as inn,
                ADRES as address,
                (SELECT COUNT(*) FROM REG_DOGOVOR rd WHERE rd.KPO = kp.KPO) as contract_count
            FROM KL_PRED kp
            ORDER BY NPO
            """

            cursor.execute(query)

            for row in cursor:
                organizations_list.append({
                    'name': row[0],
                    'code': row[1],
                    'inn': row[2],
                    'address': row[3],
                    'contract_count': row[4] or 0
                })

            cursor.close()
            conn.close()

        except Exception as e:
            flash(f'Ошибка при получении организаций: {e}', 'danger')
            print(f"Ошибка организаций: {e}")

    return render_template('organizations.html', organizations=organizations_list)


@app.route('/documents')
@login_required
def documents():
    """Документы (если есть такая таблица)"""
    conn = get_db_connection()
    documents_list = []

    if conn:
        try:
            cursor = conn.cursor()

            # Проверяем, есть ли таблица документов
            # Если нет - возвращаем пустой список

            cursor.close()
            conn.close()

        except:
            pass

    return render_template('documents.html', documents=documents_list)


@app.route('/statistics')
@login_required
def statistics():
    """Статистика"""
    conn = get_db_connection()
    stats = {
        'organizations': 0,
        'contracts': 0,
        'users': 0
    }

    if conn:
        try:
            cursor = conn.cursor()

            # Статистика по организациям
            cursor.execute("SELECT COUNT(*) FROM KL_PRED")
            stats['organizations'] = cursor.fetchone()[0]

            # Статистика по договорам (только для текущей организации)
            cursor.execute("SELECT COUNT(*) FROM REG_DOGOVOR WHERE KPO = :kpo",
                           kpo=session.get('kpo'))
            stats['contracts'] = cursor.fetchone()[0]

            # Статистика по пользователям (активные)
            cursor.execute("SELECT COUNT(*) FROM PERS_ROOM_AUT WHERE KSOST = 0")
            stats['users'] = cursor.fetchone()[0]

            cursor.close()
            conn.close()

        except Exception as e:
            print(f"Ошибка статистики: {e}")

    return render_template('statistics.html', stats=stats)


@app.route('/settings')
@login_required
def settings():
    """Настройки профиля"""
    # В ТП нет редактирования профиля, оставляем заглушку
    flash('Редактирование профиля временно недоступно', 'info')
    return redirect(url_for('profile'))


@app.route('/about')
def about():
    """О системе"""
    return render_template('about.html')


@app.route('/help')
def help_page():
    """Помощь"""
    return render_template('help.html')


@app.route('/search', methods=['GET'])
@login_required
def search():
    """Поиск по договорам и организациям"""
    query = request.args.get('q', '')
    results = {'contracts': [], 'organizations': []}

    if query:
        conn = get_db_connection()
        if conn:
            try:
                cursor = conn.cursor()

                # Поиск по договорам
                search_contracts = """
                SELECT PREDM_DOG, KPO
                FROM REG_DOGOVOR 
                WHERE KPO = :kpo 
                  AND UPPER(PREDM_DOG) LIKE UPPER(:search)
                ORDER BY PREDM_DOG
                """
                cursor.execute(search_contracts,
                               kpo=session.get('kpo'),
                               search=f'%{query}%')

                for row in cursor:
                    results['contracts'].append({
                        'subject': row[0],
                        'org_code': row[1]
                    })

                # Поиск по организациям
                search_orgs = """
                SELECT NPO, KPO, INN, ADRES
                FROM KL_PRED 
                WHERE UPPER(NPO) LIKE UPPER(:search)
                   OR KPO LIKE :search
                   OR INN LIKE :search
                ORDER BY NPO
                """
                cursor.execute(search_orgs, search=f'%{query}%')

                for row in cursor:
                    results['organizations'].append({
                        'name': row[0],
                        'code': row[1],
                        'inn': row[2],
                        'address': row[3]
                    })

                cursor.close()
                conn.close()

            except Exception as e:
                flash(f'Ошибка поиска: {e}', 'danger')

    return render_template('search.html',
                           query=query,
                           results=results,
                           total_results=len(results['contracts']) + len(results['organizations']))


@app.route('/logout')
def logout():
    """Выход из системы"""
    if 'email' in session:
        print(f"✅ Пользователь вышел: {session['email']}")

    session.clear()
    flash('Вы вышли из системы', 'info')
    return redirect(url_for('index'))


# ===== API ENDPOINTS (если нужно) =====

@app.route('/api/user-info')
@login_required
def api_user_info():
    """API: информация о пользователе"""
    return {
        'user_id': session.get('user_id'),
        'email': session.get('email'),
        'org_name': session.get('org_name'),
        'kpo': session.get('kpo')
    }


@app.route('/api/contracts')
@login_required
def api_contracts():
    """API: список договоров в JSON"""
    conn = get_db_connection()
    contracts = []

    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT PREDM_DOG, KPO
                FROM REG_DOGOVOR 
                WHERE KPO = :kpo
                ORDER BY PREDM_DOG
            """, kpo=session.get('kpo'))

            for row in cursor:
                contracts.append({
                    'subject': row[0],
                    'org_code': row[1]
                })

            cursor.close()
            conn.close()

        except:
            pass

    return {'contracts': contracts}


# ===== ERROR HANDLERS =====

@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404


@app.errorhandler(500)
def internal_server_error(e):
    return render_template('500.html'), 500


# ===== ЗАПУСК ПРИЛОЖЕНИЯ =====

if __name__ == '__main__':
    # Проверяем подключение к Oracle при запуске
    print("\nПроверка подключения к Oracle...")
    test_conn = get_db_connection()

    if test_conn:
        try:
            cursor = test_conn.cursor()

            # Проверяем доступ к таблицам
            tables_to_check = ['PERS_ROOM_AUT', 'PERS_ROOM', 'REG_DOGOVOR', 'KL_PRED']
            for table in tables_to_check:
                try:
                    cursor.execute(f"SELECT COUNT(*) FROM {table} WHERE ROWNUM <= 1")
                    print(f"✅ Таблица {table}: доступна")
                except Exception as e:
                    print(f"❌ Таблица {table}: ошибка - {str(e)[:50]}")

            cursor.close()
            test_conn.close()

        except Exception as e:
            print(f"❌ Ошибка проверки таблиц: {e}")
    else:
        print("❌ Oracle подключение: ОШИБКА")
        print("   Приложение будет работать с ограниченным функционалом")

    print("=" * 70)
    print("\nСервер запущен: http://localhost:5000")
    print("Для входа используйте данные из таблицы PERS_ROOM_AUT")
    print("Убедитесь, что KSOST = 0 (аккаунт активен)")
    print("=" * 70)

    app.run(debug=True, port=5000)