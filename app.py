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

# 修改现有路由添加登录验证
@app.route('/employee/add')
@login_required
def add_employee():
    return render_template('index.html')

@app.route('/employees')
@login_required
def employee_list():
    if not session.get('is_admin'):
        flash('需要管理员权限')
        return redirect(url_for('login'))
    
    # 获取所有在职员工及其最新工资记录
    employees = db.session.query(
        Employee,
        Salary.base_salary
    ).join(
        Salary,
        Employee.id == Salary.employee_id
    ).options(joinedload(Employee.department)  # 添加这行预加载部门
    ).filter(
        Employee.is_active == True,
        Salary.month == db.session.query(
            func.max(Salary.month)
        ).filter(
            Salary.employee_id == Employee.id
        ).correlate(Employee)
    ).all()
    
    # 按科室名称和基本工资排序
    sorted_employees = sorted(employees, 
                            key=lambda e: (e.Employee.department.name, -e.base_salary))
    
    return render_template('employee_list.html',
                         employees=sorted_employees,
                         departments=Department.query.all())

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
    
    # 获取当前月份的工资信息
    current_month = datetime.now().replace(day=1)
    salary = Salary.query.filter_by(
        employee_id=employee.id,
        month=current_month
    ).first()
    
    if not salary:
        salary = Salary(
            base_salary=0,
            benefits=0,
            bonus=0,
            insurance=0,
            housing_fund=0
        )
    
    return render_template('edit_employee.html',
                         employee=employee,
                         salary=salary,
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