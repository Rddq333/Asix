from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func
import config
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from extensions import db
from sqlalchemy.orm import joinedload
from datetime import datetime


app = Flask(__name__)
app.config.from_object(config)
db.init_app(app)

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
        user = User.query.filter_by(username=username).first()
        
        if user and check_password_hash(user.password, password):
            session['user_id'] = user.id
            session['is_admin'] = user.is_admin
            return redirect(url_for('employee_list'))
        return render_template('login.html', error='用户名或密码错误')
    return render_template('login.html')

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

# 其他路由...
# 添加在 employee_list 路由下方
@app.route('/resign/<int:id>', methods=['POST'])
@login_required
def resign_employee(id):
    if not session.get('is_admin'):
        flash('需要管理员权限')
        return redirect(url_for('login'))
    
    # 标记员工为离职
    emp = Employee.query.get_or_404(id)
    emp.is_active = False
    
    # 创建离职记录
    resign = Resignation(
        employee_id=emp.id,
        resign_date=datetime.now(),
        name=emp.name,
        department=emp.department.name,
        position=emp.position
    )
    
    db.session.add(resign)
    db.session.commit()
    
    flash(f'{emp.name} 离职登记成功')
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
        
        # 获取所有部门的工资信息，按部门排序
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

@app.before_first_request
def create_tables():
    with app.app_context():
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
            for _ in range(50):
                dept = random.choice(Department.query.all())
                
                # 创建员工
                emp = Employee(
                    name=fake.name(),  # 使用faker生成中文名
                    gender=random.choice(['男', '女']),
                    age=random.randint(22, 55),
                    position=random.choice(positions[dept.name]),
                    department=dept,
                    is_active=random.choice([True, False])
                )
                db.session.add(emp)
                db.session.commit()  # 先提交员工数据，确保有ID

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
                        position=emp.position
                    )
                    db.session.add(resign)

            db.session.commit()

        # 创建测试管理员用户
        if not User.query.first():
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