from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func
import config
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from extensions import db
from sqlalchemy.orm import joinedload
from datetime import datetime
from flask_migrate import Migrate


app = Flask(__name__)
app.config.from_object(config)
db.init_app(app)
migrate = Migrate(app, db)

# 在 db 初始化之后导入模型
from models import *

# 添加登录装饰器
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# 登录路由
@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        # 查找用户
        user = User.query.filter_by(username=username).first()
        
        if user and check_password_hash(user.password, password):
            session['user_id'] = user.id
            session['is_admin'] = user.is_admin
            
            # 如果是管理员，重定向到员工列表
            if user.is_admin:
                return redirect(url_for('employee_list'))
            else:
                # 如果是普通员工，查找对应的员工信息
                employee = Employee.query.filter_by(employee_id=username).first()
                if employee:
                    return redirect(url_for('employee_dashboard'))
                else:
                    flash('未找到对应的员工信息')
                    return redirect(url_for('logout'))
        
        flash('用户名或密码错误')
        return render_template('login.html')
    
    return render_template('login.html')

# 普通员工仪表板
@app.route('/dashboard')
@login_required
def employee_dashboard():
    if session.get('is_admin'):
        return redirect(url_for('employee_list'))
    
    user = User.query.get(session['user_id'])
    employee = Employee.query.filter_by(employee_id=user.username).first()
    
    if not employee:
        flash('未找到对应的员工信息')
        return redirect(url_for('logout'))
    
    # 获取员工最新的工资信息
    latest_salary = Salary.query.filter_by(
        employee_id=employee.id
    ).order_by(Salary.month.desc()).first()
    
    return render_template('employee_dashboard.html',
                         employee=employee,
                         salary=latest_salary)

# 提交辞职申请
@app.route('/resignation/apply', methods=['GET', 'POST'])
@login_required
def apply_resignation():
    if session.get('is_admin'):
        return redirect(url_for('employee_list'))
    
    user = User.query.get(session['user_id'])
    employee = Employee.query.filter_by(employee_id=user.username).first()
    
    if not employee:
        flash('未找到对应的员工信息')
        return redirect(url_for('logout'))
    
    if request.method == 'POST':
        try:
            resign = Resignation(
                employee_id=employee.id,
                resign_date=datetime.strptime(request.form.get('resign_date'), '%Y-%m-%d'),
                name=employee.name,
                department=employee.department.name,
                position=employee.position,
                status='pending'  # 添加状态字段：pending（待处理）
            )
            db.session.add(resign)
            db.session.commit()
            flash('辞职申请已提交，等待管理员审核')
            return redirect(url_for('employee_dashboard'))
        except Exception as e:
            db.session.rollback()
            flash(f'提交失败：{str(e)}')
    
    return render_template('apply_resignation.html', employee=employee)

# 管理员查看辞职申请列表
@app.route('/resignations')
@login_required
def resignation_list():
    if not session.get('is_admin'):
        flash('需要管理员权限')
        return redirect(url_for('login'))
    
    resignations = Resignation.query.order_by(Resignation.resign_date.desc()).all()
    return render_template('resignation_list.html', resignations=resignations)

# 管理员处理辞职申请
@app.route('/resignation/process/<int:id>', methods=['POST'])
@login_required
def process_resignation(id):
    if not session.get('is_admin'):
        flash('需要管理员权限')
        return redirect(url_for('login'))
    
    resignation = Resignation.query.get_or_404(id)
    action = request.form.get('action')
    
    if action == 'approve':
        # 更新员工状态为离职
        employee = Employee.query.get(resignation.employee_id)
        if employee:
            employee.is_active = False
            resignation.status = 'approved'
            db.session.commit()
            flash('已批准辞职申请并更新员工状态')
    elif action == 'reject':
        resignation.status = 'rejected'
        db.session.commit()
        flash('已拒绝辞职申请')
    
    return redirect(url_for('resignation_list'))

# 登出路由
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/employees')
@login_required
def employee_list():
    if not session.get('is_admin'):
        flash('需要管理员权限')
        return redirect(url_for('login'))
    
    # 获取部门筛选参数
    dept_id = request.args.get('dept', type=int)
    # 获取页码参数，默认为1
    page = request.args.get('page', 1, type=int)
    # 每页显示的员工数量
    per_page = 10
    
    # 构建基础查询
    base_query = db.session.query(
        Employee,
        Salary.base_salary,
        Salary.benefits,
        Salary.bonus,
        Salary.insurance,
        Salary.housing_fund
    ).join(
        Salary,
        Employee.id == Salary.employee_id
    ).options(joinedload(Employee.department)
    ).filter(
        Employee.is_active == True,
        Salary.month == db.session.query(
            func.max(Salary.month)
        ).filter(
            Salary.employee_id == Employee.id
        ).correlate(Employee)
    )
    
    # 如果指定了部门，添加部门筛选
    if dept_id:
        base_query = base_query.filter(Employee.department_id == dept_id)
    
    # 计算总记录数
    total = base_query.count()
    
    # 添加分页
    employees = base_query.order_by(Employee.department_id, -Salary.base_salary)\
                    .offset((page - 1) * per_page)\
                    .limit(per_page)\
                    .all()
    
    # 计算实际工资（基本工资 + 福利补贴 + 奖励工资 - 失业保险 - 住房公积金）
    employees_with_salary = []
    for emp, base_salary, benefits, bonus, insurance, housing_fund in employees:
        actual_salary = base_salary + benefits + bonus - insurance - housing_fund
        employees_with_salary.append((emp, actual_salary))
    
    # 计算总页数
    total_pages = (total + per_page - 1) // per_page
    
    return render_template('employee_list.html',
                         employees=employees_with_salary,
                         departments=Department.query.all(),
                         current_page=page,
                         total_pages=total_pages,
                         current_dept=dept_id,
                         total=total)

@app.route('/employee/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_employee(id):
    if not session.get('is_admin'):
        flash('需要管理员权限')
        return redirect(url_for('login'))
    
    employee = Employee.query.get_or_404(id)
    
    if request.method == 'POST':
        try:
            # 更新员工基本信息
            employee.name = request.form.get('name')
            employee.gender = request.form.get('gender')
            employee.age = int(request.form.get('age'))
            employee.position = request.form.get('position')
            department_id = int(request.form.get('department_id'))
            employee.department_id = department_id
            
            # 更新工资信息
            current_month = datetime.now().replace(day=1)
            salary = Salary.query.filter_by(
                employee_id=employee.id,
                month=current_month
            ).first()
            
            if not salary:
                salary = Salary(employee_id=employee.id, month=current_month)
                db.session.add(salary)
            
            salary.base_salary = float(request.form.get('base_salary'))
            salary.benefits = float(request.form.get('benefits'))
            salary.bonus = float(request.form.get('bonus'))
            salary.insurance = float(request.form.get('insurance'))
            salary.housing_fund = float(request.form.get('housing_fund'))
            
            db.session.commit()
            flash('员工信息更新成功！')
            return redirect(url_for('employee_list'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'更新失败：{str(e)}')
    
    # 获取最新的工资信息
    latest_salary = Salary.query.filter_by(
        employee_id=employee.id
    ).order_by(Salary.month.desc()).first()
    
    if not latest_salary:
        latest_salary = Salary(
            base_salary=0,
            benefits=0,
            bonus=0,
            insurance=0,
            housing_fund=0
        )
    
    return render_template('edit_employee.html',
                         employee=employee,
                         salary=latest_salary,
                         departments=Department.query.all())

@app.route('/resign/<int:id>', methods=['POST'])
@login_required
def resign_employee(id):
    if not session.get('is_admin'):
        flash('需要管理员权限')
        return redirect(url_for('login'))
    employee = Employee.query.get_or_404(id)
    employee.is_active = False
    resign = Resignation(
        employee_id=employee.id,
        resign_date=datetime.now(),
        name=employee.name,
        department=employee.department.name,
        position=employee.position
    )
    db.session.add(resign)
    db.session.commit()
    flash('离职登记成功')
    return redirect(url_for('employee_list'))

@app.route('/employee/add', methods=['GET', 'POST'])
@login_required
def add_employee():
    if not session.get('is_admin'):
        flash('需要管理员权限')
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        try:
            # 创建新员工
            employee = Employee(
                name=request.form.get('name'),
                gender=request.form.get('gender'),
                age=int(request.form.get('age')),
                position=request.form.get('position'),
                department_id=int(request.form.get('department_id')),
                is_active=True
            )
            db.session.add(employee)
            db.session.flush()  # 获取新员工的ID
            
            # 创建工资记录
            current_month = datetime.now().replace(day=1)
            salary = Salary(
                employee_id=employee.id,
                month=current_month,
                base_salary=float(request.form.get('base_salary')),
                benefits=float(request.form.get('benefits')),
                bonus=float(request.form.get('bonus')),
                insurance=float(request.form.get('insurance')),
                housing_fund=float(request.form.get('housing_fund'))
            )
            db.session.add(salary)
            
            db.session.commit()
            flash('新员工添加成功！')
            return redirect(url_for('employee_list'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'添加失败：{str(e)}')
    
    return render_template('add_employee.html',
                         departments=Department.query.all())

@app.route('/salary/input', methods=['GET', 'POST'])
@login_required
def salary_input():
    if not session.get('is_admin'):
        flash('需要管理员权限')
        return redirect(url_for('login'))
    
    # 获取部门筛选参数
    dept_id = request.args.get('dept', type=int)
    # 获取月份参数，默认为当前月
    month = request.args.get('month', datetime.now().strftime('%Y-%m'))
    # 获取页码参数，默认为1
    page = request.args.get('page', 1, type=int)
    # 每页显示的员工数量
    per_page = 10
    
    if request.method == 'POST':
        try:
            # 获取表单数据
            employee_id = int(request.form.get('employee_id'))
            base_salary = float(request.form.get('base_salary'))
            benefits = float(request.form.get('benefits'))
            bonus = float(request.form.get('bonus'))
            insurance = float(request.form.get('insurance'))
            housing_fund = float(request.form.get('housing_fund'))
            salary_month = datetime.strptime(request.form.get('month'), '%Y-%m')
            
            # 检查是否已存在该月的工资记录
            existing_salary = Salary.query.filter_by(
                employee_id=employee_id,
                month=salary_month
            ).first()
            
            if existing_salary:
                # 更新现有记录
                existing_salary.base_salary = base_salary
                existing_salary.benefits = benefits
                existing_salary.bonus = bonus
                existing_salary.insurance = insurance
                existing_salary.housing_fund = housing_fund
            else:
                # 创建新记录
                salary = Salary(
                    employee_id=employee_id,
                    month=salary_month,
                    base_salary=base_salary,
                    benefits=benefits,
                    bonus=bonus,
                    insurance=insurance,
                    housing_fund=housing_fund
                )
                db.session.add(salary)
            
            db.session.commit()
            flash('工资信息保存成功！')
            return redirect(url_for('salary_input', dept=dept_id, month=month, page=page))
            
        except Exception as e:
            db.session.rollback()
            flash(f'保存失败：{str(e)}')
    
    # 获取指定月份
    current_month_date = datetime.strptime(month, '%Y-%m')
    
    # 构建基础查询，关联salary表
    query = db.session.query(Employee).outerjoin(
        Salary,
        db.and_(
            Employee.id == Salary.employee_id,
            Salary.month == current_month_date
        )
    ).filter(Employee.is_active == True)
    
    if dept_id:
        query = query.filter(Employee.department_id == dept_id)
    
    # 计算总记录数
    total = query.count()
    
    # 添加分页和排序
    # 使用CASE语句处理NULL值，将NULL值转换为0
    employees = query.order_by(
        Employee.department_id,
        db.case(
            (Salary.base_salary.is_(None), 0),
            else_=Salary.base_salary
        ).desc()
    ).offset((page - 1) * per_page).limit(per_page).all()
    
    # 获取每个员工指定月份的工资信息
    employee_salaries = {}
    for emp in employees:
        salary = Salary.query.filter_by(
            employee_id=emp.id,
            month=current_month_date
        ).first()
        employee_salaries[emp.id] = salary
    
    # 计算总页数
    total_pages = (total + per_page - 1) // per_page
    
    return render_template('salary_input.html',
                         employees=employees,
                         employee_salaries=employee_salaries,
                         departments=Department.query.all(),
                         current_dept=dept_id,
                         current_month=month,
                         current_page=page,
                         total_pages=total_pages,
                         total=total,
                         per_page=per_page)

@app.route('/salary/history/<int:employee_id>')
@login_required
def salary_history(employee_id):
    if not session.get('is_admin'):
        flash('需要管理员权限')
        return redirect(url_for('login'))
    
    employee = Employee.query.get_or_404(employee_id)
    
    # 获取该员工的所有工资记录，按月份降序排列
    salaries = Salary.query.filter_by(
        employee_id=employee_id
    ).order_by(Salary.month.desc()).all()
    
    # 计算每月的实际工资
    salary_history = []
    yearly_stats = {}
    
    for salary in salaries:
        actual_salary = salary.base_salary + salary.benefits + salary.bonus - salary.insurance - salary.housing_fund
        salary_history.append({
            'month': salary.month,
            'base_salary': salary.base_salary,
            'benefits': salary.benefits,
            'bonus': salary.bonus,
            'insurance': salary.insurance,
            'housing_fund': salary.housing_fund,
            'actual_salary': actual_salary
        })
        
        # 计算年度统计
        year = salary.month.year
        if year not in yearly_stats:
            yearly_stats[year] = {
                'base_salary': 0,
                'benefits': 0,
                'bonus': 0,
                'insurance': 0,
                'housing_fund': 0,
                'actual_salary': 0
            }
        
        yearly_stats[year]['base_salary'] += salary.base_salary
        yearly_stats[year]['benefits'] += salary.benefits
        yearly_stats[year]['bonus'] += salary.bonus
        yearly_stats[year]['insurance'] += salary.insurance
        yearly_stats[year]['housing_fund'] += salary.housing_fund
        yearly_stats[year]['actual_salary'] += actual_salary
    
    return render_template('salary_history.html',
                         employee=employee,
                         salary_history=salary_history,
                         yearly_stats=yearly_stats)

@app.route('/salary/report/<month>')
@login_required
def salary_report(month):
    if not session.get('is_admin'):
        flash('需要管理员权限')
        return redirect(url_for('login'))
    
    try:
        # 将月份字符串转换为datetime对象
        report_month = datetime.strptime(month, '%Y-%m')
        
        # 获取所有部门的工资信息，按部门ID排序
        departments = Department.query.order_by(Department.id).all()
        
        # 存储每个部门的工资信息
        dept_salaries = {}
        total_salary = 0
        
        for dept in departments:
            # 获取该部门所有在职员工的工资信息
            employees = Employee.query.filter_by(
                department_id=dept.id,
                is_active=True
            ).all()
            
            dept_employees = []
            dept_total = 0
            
            for emp in employees:
                salary = Salary.query.filter_by(
                    employee_id=emp.id,
                    month=report_month
                ).first()
                
                if salary:
                    actual_salary = salary.base_salary + salary.benefits + salary.bonus - salary.insurance - salary.housing_fund
                    dept_employees.append({
                        'name': emp.name,
                        'position': emp.position,
                        'base_salary': salary.base_salary,
                        'benefits': salary.benefits,
                        'bonus': salary.bonus,
                        'insurance': salary.insurance,
                        'housing_fund': salary.housing_fund,
                        'actual_salary': actual_salary
                    })
                    dept_total += actual_salary
            
            # 按基本工资降序排序
            dept_employees.sort(key=lambda x: x['base_salary'], reverse=True)
            
            if dept_employees:  # 只添加有员工的部门
                dept_salaries[dept.name] = {
                    'employees': dept_employees,
                    'total': dept_total
                }
                total_salary += dept_total
        
        return render_template('salary_report.html',
                             month=month,
                             dept_salaries=dept_salaries,
                             total_salary=total_salary)
                             
    except ValueError:
        flash('无效的月份格式')
        return redirect(url_for('salary_input'))

@app.route('/salary/statistics')
@login_required
def salary_statistics():
    if not session.get('is_admin'):
        flash('需要管理员权限')
        return redirect(url_for('login'))
    
    # 获取查询参数
    month = request.args.get('month')
    dept_id = request.args.get('dept', type=int)
    position = request.args.get('position')
    
    # 科室和职位的对应关系
    dept_positions = {
        '经理室': ['总经理', '副总经理', '行政经理'],
        '财务科': ['会计', '出纳', '财务主管'],
        '技术科': ['工程师', '架构师', '技术总监'],
        '销售科': ['销售代表', '大区经理', '客户经理']
    }
    
    # 验证科室和职位的对应关系
    if dept_id and position:
        dept = Department.query.get(dept_id)
        if dept and position not in dept_positions.get(dept.name, []):
            flash(f'错误：{dept.name}没有{position}这个职位')
            return redirect(url_for('salary_statistics'))
    
    # 构建基础查询
    query = db.session.query(
        Employee,
        Salary,
        Department
    ).join(
        Salary,
        Employee.id == Salary.employee_id
    ).join(
        Department,
        Employee.department_id == Department.id
    ).filter(
        Employee.is_active == True
    )
    
    # 应用筛选条件
    if month:
        month_date = datetime.strptime(month, '%Y-%m')
        query = query.filter(Salary.month == month_date)
    
    if dept_id:
        query = query.filter(Employee.department_id == dept_id)
    
    if position:
        query = query.filter(Employee.position == position)
    
    # 执行查询
    results = query.all()
    
    # 统计数据
    stats = {
        'total_employees': 0,
        'total_base_salary': 0,
        'total_benefits': 0,
        'total_bonus': 0,
        'total_insurance': 0,
        'total_housing_fund': 0,
        'total_actual_salary': 0,
        'by_department': {},
        'by_position': {}
    }
    
    for emp, salary, dept in results:
        actual_salary = salary.base_salary + salary.benefits + salary.bonus - salary.insurance - salary.housing_fund
        
        # 更新总计
        stats['total_employees'] += 1
        stats['total_base_salary'] += salary.base_salary
        stats['total_benefits'] += salary.benefits
        stats['total_bonus'] += salary.bonus
        stats['total_insurance'] += salary.insurance
        stats['total_housing_fund'] += salary.housing_fund
        stats['total_actual_salary'] += actual_salary
        
        # 按部门统计
        if dept.name not in stats['by_department']:
            stats['by_department'][dept.name] = {
                'count': 0,
                'total_salary': 0
            }
        stats['by_department'][dept.name]['count'] += 1
        stats['by_department'][dept.name]['total_salary'] += actual_salary
        
        # 按职位统计
        if emp.position not in stats['by_position']:
            stats['by_position'][emp.position] = {
                'count': 0,
                'total_salary': 0
            }
        stats['by_position'][emp.position]['count'] += 1
        stats['by_position'][emp.position]['total_salary'] += actual_salary
    
    # 获取所有职位，但按科室分组
    positions_by_dept = {}
    for dept in Department.query.all():
        positions_by_dept[dept.name] = dept_positions.get(dept.name, [])
    
    return render_template('salary_statistics.html',
                         stats=stats,
                         departments=Department.query.all(),
                         positions_by_dept=positions_by_dept,
                         current_month=month,
                         current_dept=dept_id,
                         current_position=position)

@app.route('/resigned/employees')
@login_required
def resigned_employees():
    if not session.get('is_admin'):
        flash('需要管理员权限')
        return redirect(url_for('login'))
    
    # 获取查询参数
    name = request.args.get('name', '')
    dept_id = request.args.get('dept', type=int)
    resign_date = request.args.get('resign_date', '')
    
    # 构建基础查询
    query = Resignation.query.join(
        Employee,
        Resignation.employee_id == Employee.id
    ).join(
        Department,
        Employee.department_id == Department.id
    )
    
    # 应用筛选条件
    if name:
        query = query.filter(Resignation.name.like(f'%{name}%'))
    if dept_id:
        query = query.filter(Employee.department_id == dept_id)
    if resign_date:
        try:
            date = datetime.strptime(resign_date, '%Y-%m')
            query = query.filter(
                db.func.date_format(Resignation.resign_date, '%Y-%m') == resign_date
            )
        except ValueError:
            flash('无效的日期格式')
    
    # 执行查询并按辞职日期降序排序
    resignations = query.order_by(Resignation.resign_date.desc()).all()
    
    # 获取每个辞职员工的工资历史
    resigned_employees = []
    for resign in resignations:
        employee = Employee.query.get(resign.employee_id)
        if employee:
            # 获取该员工的所有工资记录
            salaries = Salary.query.filter_by(
                employee_id=employee.id
            ).order_by(Salary.month.desc()).all()
            
            # 计算工资历史
            salary_history = []
            for salary in salaries:
                actual_salary = salary.base_salary + salary.benefits + salary.bonus - salary.insurance - salary.housing_fund
                salary_history.append({
                    'month': salary.month,
                    'base_salary': salary.base_salary,
                    'benefits': salary.benefits,
                    'bonus': salary.bonus,
                    'insurance': salary.insurance,
                    'housing_fund': salary.housing_fund,
                    'actual_salary': actual_salary
                })
            
            resigned_employees.append({
                'resignation': resign,
                'employee': employee,
                'salary_history': salary_history
            })
    
    return render_template('resigned_employees.html',
                         resigned_employees=resigned_employees,
                         departments=Department.query.all(),
                         current_name=name,
                         current_dept=dept_id,
                         current_date=resign_date)

@app.before_first_request
def create_tables():
    with app.app_context():
        # 删除所有表
        db.drop_all()
        # 创建所有表
        db.create_all()
        
        # 初始化部门
        departments = ['经理室', '财务科', '技术科', '销售科']
        for dept in departments:
            if not Department.query.filter_by(name=dept).first():
                db.session.add(Department(name=dept))
        db.session.commit()

        # 生成测试员工（50个）和工资数据
        if not Employee.query.first():
            from datetime import datetime, timedelta
            import random
            from faker import Faker  # 建议使用faker库生成更真实的数据
            
            fake = Faker('zh_CN')
            
            # 职位映射
            positions = {
                '经理室': ['总经理', '副总经理', '行政经理'],
                '财务科': ['会计', '出纳', '财务主管'],
                '技术科': ['工程师', '架构师', '技术总监'],
                '销售科': ['销售代表', '大区经理', '客户经理']
            }
            
            # 生成50个员工
            for i in range(50):
                dept = random.choice(Department.query.all())
                
                # 生成6位工号（从100001开始）
                employee_id = str(100001 + i)
                
                # 创建员工
                emp = Employee(
                    employee_id=employee_id,
                    name=fake.name(),  # 使用faker生成中文名
                    gender=random.choice(['男', '女']),
                    age=random.randint(22, 55),
                    position=random.choice(positions[dept.name]),
                    department=dept,
                    is_active=random.choice([True, False])
                )
                db.session.add(emp)
                db.session.commit()  # 先提交员工数据，确保有ID

                # 为每个员工创建用户账号
                user = User(
                    username=employee_id,  # 使用工号作为用户名
                    password=generate_password_hash('123456'),  # 默认密码123456
                    is_admin=False,
                    department_id=dept.id
                )
                db.session.add(user)

                # 为每个员工生成12个月的工资记录
                for month in range(1, 13):
                    salary = Salary(
                        base_salary=round(random.uniform(2000, 3000), 2),
                        benefits=round(random.uniform(500, 1500), 2),
                        bonus=round(random.uniform(0, 1000), 2),
                        insurance=round(random.uniform(100, 500), 2),
                        housing_fund=round(random.uniform(200, 800), 2),
                        month=datetime(2023, month, 1),
                        employee_id=emp.id
                    )
                    db.session.add(salary)

                # 如果是离职员工，有30%概率生成离职记录
                if not emp.is_active and random.random() < 0.3:
                    resign_date = datetime(2023, random.randint(1, 12), random.randint(1, 28))
                    resign = Resignation(
                        employee_id=emp.id,
                        resign_date=resign_date,
                        name=emp.name,
                        department=dept.name,
                        position=emp.position,
                        status='approved'  # 添加状态字段
                    )
                    db.session.add(resign)

            db.session.commit()

        # 创建测试管理员用户
        if not User.query.filter_by(is_admin=True).first():
            admin_dept = Department.query.filter_by(name='经理室').first()
            admin = User(
                username='admin',
                password=generate_password_hash('123456'),
                is_admin=True,
                department_id=admin_dept.id
            )
            db.session.add(admin)
            db.session.commit()

if __name__ == '__main__':
    app.run(debug=True)