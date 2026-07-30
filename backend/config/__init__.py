import pymysql

# Django's MySQL backend imports the mysqlclient-compatible MySQLdb module.
pymysql.version_info = (1, 4, 6, 'final', 0)
pymysql.install_as_MySQLdb()
