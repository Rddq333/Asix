from extensions import db

class Department(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(20), unique=True, nullable=False)
    employees = db.relationship('Employee', backref='department', lazy=True)

class Employee(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(20), nullable=False)
    gender = db.Column(db.String(2), nullable=False)
    age = db.Column(db.Integer, nullable=False)
    position = db.Column(db.String(20), nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    department_id = db.Column(db.Integer, db.ForeignKey('department.id'))
    salaries = db.relationship('Salary', backref='employee', lazy=True)

class Salary(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    base_salary = db.Column(db.Numeric(10,2), nullable=False)
    benefits = db.Column(db.Numeric(10,2), default=0)
    bonus = db.Column(db.Numeric(10,2), default=0)
    insurance = db.Column(db.Numeric(10,2), default=0)
    housing_fund = db.Column(db.Numeric(10,2), default=0)
    month = db.Column(db.Date, nullable=False)
    employee_id = db.Column(db.Integer, db.ForeignKey('employee.id'))
    
class Resignation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, nullable=False)
    resign_date = db.Column(db.Date, nullable=False)
    name = db.Column(db.String(20))
    department = db.Column(db.String(20))
    position = db.Column(db.String(20))


# 需要确保User模型中的password字段长度设置为256
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(20), unique=True, nullable=False)
    password = db.Column(db.String(256))  # 必须保持256字符长度
    is_admin = db.Column(db.Boolean, default=False)
    department_id = db.Column(db.Integer, db.ForeignKey('department.id'))