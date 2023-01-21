import uuid

from flask import Flask, jsonify, request
from neo4j import GraphDatabase
from dotenv import load_dotenv
import socket
import sys

load_dotenv()
import os

app = Flask(__name__)

uri = os.getenv("URI")
user = os.getenv("USER")
password = os.getenv("PASSWORD")
print(uri, user, password)
driver = GraphDatabase.driver(uri, auth=(user, password), database="neo4j")


def get_employees(tx):
    query = "MATCH (m:Employee) RETURN m"
    results = tx.run(query).data()
    employees = [
        {
            "name": result['m']['name'],
            "surname": result['m']['surname'],
            "post": result['m']['post']
        } for result in results
    ]
    return employees

def get_employee(tx, id):
    query = "MATCH (e:Employee) WHERE ID(e)=$id RETURN e"
    employee = tx.run(query, id=id).data()
    #print(employee)

    if len(employee) == 0:
        return None
    else:
        return employee.data()


@app.route('/employees', methods=['GET'])
def get_employees_route():
    with driver.session() as session:
        # I have got "read_transaction was renamed to execute_read" warning!
        employees = session.execute_read(get_employees)
        # employees = session.read_transaction(get_employees)
    # check for sort query parameters
    if request.args.get('sortByName') == "1":
        employees.sort(key=lambda x: x['name'], reverse=True)
    if request.args.get('sortBySurname') == "1":
        employees.sort(key=lambda x: x['surname'], reverse=True)
    if request.args.get('sortByPost') == "1":
        employees.sort(key=lambda x: x['post'], reverse=True)
    if request.args.get('sortByName') == "-1":
        employees.sort(key=lambda x: x['name'], reverse=False)
    if request.args.get('sortBySurname') == "-1":
        employees.sort(key=lambda x: x['surname'], reverse=False)
    if request.args.get('sortByPost') == "-1":
        employees.sort(key=lambda x: x['post'], reverse=False)
    # check for filter query parameters
    if request.args.get('filterByName') is not None:
        name = request.args.get('filterByName')
        employees = [employee for employee in employees if employee['name'] == name]
    if request.args.get('filterBySurname') is not None:
        surname = request.args.get('filterBySurname')
        employees = [employee for employee in employees if employee['surname'] == surname]
    if request.args.get('filterByPost') is not None:
        post = request.args.get('filterByPost')
        employees = [employee for employee in employees if employee['post'] == post]

    response = {'employees': employees}
    return jsonify(response)


def add_employee(tx, name, surname, post, department):
    query = "CREATE (e:Employee {name: $name, surname: $surname, post: $post})"
    query2 = "MATCH (a:Employee), (b:Department) WHERE a.name=$name AND a.surname=$surname AND b.name=$department CREATE (a)-[r:WORKS_IN]->(b)"
    # query = "CREATE (m:Movie {title: $title, released: $released})"
    tx.run(query, name=name, surname=surname, post=post)
    tx.run(query2, name=name, surname=surname, department=department)


@app.route('/employees', methods=['POST'])
def add_employee_route():
    name = request.json['name']
    surname = request.json['surname']
    post = request.json['post']
    department = request.json['department']

    with driver.session() as session:
        employees = session.execute_read(get_employees)
    similar_names = [employee for employee in employees if employee['name'] == name]
    similar_surnames = [employee for employee in employees if employee['surname'] == surname]
    # response = {'status': 'success'}  żeby na 100% nie było błedu z undefined
    if len(similar_names) == 0 and len(similar_surnames) == 0 and post is not None and department is not None:
        with driver.session() as session:
            session.write_transaction(add_employee, name, surname, post, department)
            response = {'status': 'success'}
    else:
        response = {'status': 'failure'}
    #return jsonify(response)
    print(response)
    return jsonify(response)

#5
def update_employee(tx, id, new_name, new_surname, new_post, new_department):

    query = "MATCH (e:Employee) WHERE ID(e)=$id SET e.name=$new_name, e.surname=$new_surname, e.post=$new_post"
    query_check_if_manager = "MATCH (e:Employee)-[r:MANAGES]->(d:Department) WHERE ID(e)=$id RETURN e,r,d"
    query_get_curr_department = "MATCH (e:Employee)-[r:WORKS_IN]->(d:Department) WHERE ID(e)=$id RETURN d"
    curr_department_name = tx.run(query_get_curr_department, id=id).data()[0]['d']['name']

    query2 = "MATCH (e:Employee)-[r:WORKS_IN]->() WHERE ID(e)=$id DELETE r"
    tx.run(query2, id=id)

    #tx.run(query2, id=id)
    query3 = "MATCH (e:Employee), (d:Department) WHERE ID(e)=$id AND d.name=$new_department CREATE (e)-[r:WORKS_IN]->(d)"
    tx.run(query, id=id, new_name=new_name, new_surname=new_surname, new_post=new_post)
    is_manager = tx.run(query_check_if_manager, id=id).data()#[0]['r']
    print(is_manager, 'is_manager')
    if len(is_manager) != 0:
        print(curr_department_name+'curr_department_name')
        query_get_new_manager = "MATCH (e:Employee)-[r:WORKS_IN]->(d:Department) WHERE d.name=$curr_department AND NOT e.name=$new_name AND NOT e.surname=$new_surname RETURN e ORDER BY e.name LIMIT 1"
        new_manager = tx.run(query_get_new_manager, curr_department=curr_department_name, new_name=new_name, new_surname=new_surname).data()
        if len(new_manager) != 0:
            query_delete_curr_manager = "MATCH (e:Employee)-[r:MANAGES]->(d:Department) WHERE d.name=$curr_department DELETE r"
            query_set_new_manager = "MATCH (e:Employee), (d:Department) WHERE d.name=$curr_department AND e.name=$name AND e.surname=$surname CREATE (e)-[r:MANAGES]->(d) return e"
            tx.run(query_delete_curr_manager, curr_department=curr_department_name)
            tx.run(query_set_new_manager, curr_department=curr_department_name, name=new_manager[0]['e']['name'], surname=new_manager[0]['e']['surname'])
            print('changes manager')
        else:
            query_delete_md = "MATCH (e:Employee)-[r:MANAGES]->(d:Department) WHERE d.name=$curr_department DELETE r, d"
            tx.run(query_delete_md, curr_department=curr_department_name)
            print('annihilation')
    tx.run(query3, id=id, new_department=new_department)
    return {'name': new_name, 'surname': new_surname, 'post': new_post, 'department': new_department}
    #tutaj coś straszne dzije się, bo pisałem ten kod o 01:00 i po prostu chciałem, żeby on działał i nie zajmowałem się go optymizacją


@app.route('/employees/<int:user_id>', methods=['PUT'])
def update_employee_route(user_id):
    new_name = request.json['name']
    new_surname = request.json['surname']
    new_post = request.json['post']
    new_department = request.json['department']
    #check if you changed name and surname
    with driver.session() as session:
        curr_employee = session.execute_read(get_employee, user_id)
    if not curr_employee:
        response = {'message': 'Employee not found'}
        return jsonify(response), 404
    else:
        with driver.session() as session:
            employees = session.execute_read(get_employees)
        similar_names = [employee for employee in employees if employee['name'] == new_name]
        similar_surnames = [employee for employee in employees if employee['surname'] == new_surname]

        print(curr_employee)
        if curr_employee[0]['e']['name'] == new_name:
            n_amount = 1
        else:
            n_amount = 0
        if curr_employee[0]['e']['surname'] == new_surname:
            sn_amount = 1
        else:
            sn_amount = 0

        #print(n_amount, sn_amount)

        #print(len(similar_names), len(similar_surnames))
        if len(similar_names) == n_amount and len(similar_surnames) == sn_amount and new_post is not None and new_department is not None:
            with driver.session() as session:
                session.write_transaction(update_employee, user_id, new_name, new_surname, new_post, new_department)
            response = {'status': 'success'}
        else:
            response = {'status': 'failure with form'}

    return jsonify(response)

#6

def delete_employee(tx, id):
    query = "MATCH (e:Employee) WHERE ID(e)=$id RETURN e"
    result = tx.run(query, id=id).data()

    #if not result: => to nic nie sprawdz, bo result to array
    if len(result) == 0:
        return None
    else:
        query_check_if_manager = "MATCH (e:Employee)-[r:MANAGES]->(d:Department) WHERE ID(e)=$id RETURN e,r,d"
        query_get_curr_department = "MATCH (e:Employee)-[r:WORKS_IN]->(d:Department) WHERE ID(e)=$id RETURN d"
        curr_department_name = tx.run(query_get_curr_department, id=id).data()[0]['d']['name']

        query2 = "MATCH (e:Employee)-[r:WORKS_IN]->() WHERE ID(e)=$id DELETE r"
        tx.run(query2, id=id)

        is_manager = tx.run(query_check_if_manager, id=id, ).data()  # [0]['r']
        print(is_manager, 'is_manager')
        if len(is_manager) != 0:
            query_delete_user = "MATCH (e:Employee)-[r:MANAGES]->(d:Department) WHERE ID(e)=$id AND d.name=$curr_department_name DELETE r, e"
            tx.run(query_delete_user, id=id, curr_department_name=curr_department_name)
            #deleted MANAGES and Manager
            query_get_new_manager = "MATCH (e:Employee)-[r:WORKS_IN]->(d:Department) WHERE d.name=$curr_department RETURN e ORDER BY e.name LIMIT 1"
            new_manager = tx.run(query_get_new_manager, curr_department=curr_department_name).data()
            if len(new_manager) != 0:
                query_set_new_manager = "MATCH (e:Employee), (d:Department) WHERE d.name=$curr_department AND e.name=$name AND e.surname=$surname CREATE (e)-[r:MANAGES]->(d) return e"
                tx.run(query_set_new_manager, curr_department=curr_department_name, name=new_manager[0]['e']['name'], surname=new_manager[0]['e']['surname'])
                #set new manager
            else:
                query_delete_d = "MATCH (d:Department) WHERE d.name=$curr_department DELETE d"
                tx.run(query_delete_d, curr_department=curr_department_name)
                #annihilation
        else:
            query_delete_user = "MATCH (e:Employee) WHERE ID(e)=$id DELETE e"
            tx.run(query_delete_user, id=id)

        return {'id': id}

@app.route('/employees/<int:user_id>', methods=['DELETE'])
def delete_employee_route(user_id):
    with driver.session() as session:
        employee = session.write_transaction(delete_employee, user_id)

    if not employee:
        response = {'message': 'Employee not found'}
        return jsonify(response), 404
    else:
        response = {'status': 'success'}
        return jsonify(response)

#7

def show_subordinates(tx, id):
    query = "MATCH (e:Employee) WHERE ID(e)=$id RETURN e"
    result = tx.run(query, id=id).data()

    if len(result) == 0:
        return None
    else:
        query_get_department = "MATCH (e:Employee)-[r:MANAGES]-(d:Department) WHERE ID(e)=$id RETURN d"
        department = tx.run(query_get_department, id=id).data()
        if len(department) == 0:
            return {"subordinates": "None"}
        else:
            query_get_subordinates = "MATCH (e:Employee)-[r:WORKS_IN]-(d:Department) WHERE d.name=$curr_department AND NOT ID(e)=$id RETURN e"
            subordinates = tx.run(query_get_subordinates, curr_department=department[0]['d']['name'], id=id).data()
            return {"subordinates": subordinates}

@app.route('/employees/<int:user_id>/subordinates', methods=['GET'])
def show_subordinates_of_employee_route(user_id):
    with driver.session() as session:
        response = session.execute_read(show_subordinates, user_id)

    if not response:
        response = {"failure": "user not found"}
        return jsonify(response), 404
    else:
        return jsonify(response)


#8

def show_department_of_employee(tx, id):
    query = "MATCH (e:Employee) WHERE ID(e)=$id RETURN e"
    result = tx.run(query, id=id).data()

    if len(result) == 0:
        return None
    else:
        query_get_department = "MATCH (e:Employee)-[r:WORKS_IN]-(d:Department) WHERE ID(e)=$id RETURN d"
        department = tx.run(query_get_department, id=id).data()
        department_name = department[0]['d']['name']

        query_get_coworkers = "MATCH (e:Employee)-[r:WORKS_IN]-(d:Department) WHERE d.name=$curr_department RETURN e"
        coworkers = tx.run(query_get_coworkers, curr_department=department_name).data()

        query_get_manager= "MATCH (manager:Employee)-[r:MANAGES]-(d:Department) WHERE d.name=$curr_department RETURN manager"
        manager = tx.run(query_get_manager, curr_department=department_name).data()

        return {
            'department': department_name,
            'manager': manager,
            'coworkers': coworkers
        }

@app.route('/employees/<int:user_id>/department', methods=['GET'])
def show_department_of_employee_route(user_id):
    with driver.session() as session:
        response = session.execute_read(show_department_of_employee, user_id)

    if not response:
        response = {"failure": "user not found"}
        return jsonify(response), 404
    else:
        return jsonify(response)

#9
def get_departments(tx):
    query = "MATCH (e:Employee)-[r:WORKS_IN]->(d:Department) RETURN r, d"
    results = tx.run(query).data()

    department_names = list(set([
        result['d']['name'] for result in results
    ]))

    response = []
    for department_name in department_names:
        response.append({"name": department_name, "amount_of_workers": 0})

    for elem in response:
        for result in results:
            if result['d']['name'] == elem['name']:
                elem['amount_of_workers'] += 1

    return response

@app.route('/departments', methods=['GET'])
def get_departments_route():
    with driver.session() as session:
        departments = session.execute_read(get_departments)
    # check for sort query parameters
    if request.args.get('sortByName') == "1":
        departments.sort(key=lambda x: x['name'], reverse=True)
    if request.args.get('sortByAmountOfWorkers') == "1":
        departments.sort(key=lambda x: x['amount_of_workers'], reverse=True)
    if request.args.get('sortByName') == "-1":
        departments.sort(key=lambda x: x['name'], reverse=False)
    if request.args.get('sortByAmountOfWorkers') == "-1":
        departments.sort(key=lambda x: x['amount_of_workers'], reverse=False)
    # check for filter query parameters
    if request.args.get('filterByName') is not None:
        name = request.args.get('filterByName')
        departments = [department for department in departments if department['name'] == name]
    if request.args.get('filterByAmountOfWorkers') is not None:
        amount = int(request.args.get('filterByAmountOfWorkers'))
        departments = [department for department in departments if department['amount_of_workers'] >= amount]

    response = {'departments': departments}
    return jsonify(response)

#10

def get_department_employees(tx, id):
    query = "MATCH (e:Employee)-[r:WORKS_IN]->(d:Department) WHERE ID(d)=$id RETURN d"
    result = tx.run(query, id=id).data()
    print(result)

    if len(result) == 0:
        return None
    else:
        query_department = "MATCH (e:Employee)-[r:WORKS_IN]->(d:Department) WHERE ID(d)=$id RETURN e"
        response = tx.run(query_department, id=id).data()
        return response

@app.route('/departments/<int:department_id>/employees', methods=['GET'])
def get_department_employees_route(department_id):
    with driver.session() as session:
        response = session.execute_read(get_department_employees, department_id)

    if not response:
        response = {"failure": "department not found"}
        return jsonify(response), 404
    else:
        return jsonify(response)

if __name__ == '__main__':
    app.run()
