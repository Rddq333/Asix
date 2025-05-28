import os

# 数据库配置
SQLALCHEMY_DATABASE_URI = 'mysql+pymysql://root:root@localhost/salary_management'
SQLALCHEMY_TRACK_MODIFICATIONS = False

# Flask 配置
SECRET_KEY = os.environ.get('SECRET_KEY')  # 从环境变量中读取 SECRET_KEY
#print(SECRET_KEY)  # 在系统变量中设置了SECRET_KEY