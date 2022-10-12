import json
import logging
from flask import Flask, render_template, request, redirect, url_for
from datetime import date
from src import dbdata, tablegenerator, formatprices, webwork
from src.connection import dbconnector

# create flask app
app = Flask(__name__, static_url_path='/static')
UserID = 0


@app.route('/')
def index():
    return redirect(url_for('register'))


@app.route('/register')
def register():
    return render_template("register.html")


@app.route("/home", methods=["POST", "GET"])  # TODO: Display VName in HTML
def home():
    if request.method == "POST":
        if '/register' in request.referrer:
            logging.debug("Post from login")
            return webwork.signup_in(request)
        elif '/stays' in request.referrer:
            logging.debug("Post from stays")
            webwork.stay(request)
            return redirect(url_for('home'))

    return render_template("error.html")


@app.route("/stays")
def stays():
    uid = get_uid_from_cookie()
    vname = dbdata.get_vname_by_id(uid)
    nname = dbdata.get_nname_by_id(uid)
    counter = dbdata.get_stay_counter_by_id(uid)
    start, end = dbdata.get_stay_start_end_by_id(uid)
    return render_template("stays.html", counter=counter, vname=vname, nname=nname, start=start, end=end)


@app.route("/bill")
def bill():
    return webwork.billing()


@app.route("/get-cookies/UserID")
def get_uid_from_cookie():
    logging.debug("UserID: " + request.cookies.get("UserID"))
    return request.cookies.get("UserID")  # returns the UserID cookie


@app.route("/get-Vname-by-ID")
def get_vname_by_id():
    ID = request.cookies.get("UserID")
    sql_statement = f"SELECT VNAME FROM NAME WHERE ID = {ID}"
    logging.debug(json.dumps(dbconnector.sql(sql_statement)))
    return str(json.dumps(dbconnector.sql(sql_statement)))


@app.route("/drinkselector")  # TODO: Make it possible to send the data to the database
def drinkselector():
    water_data = dbconnector.sql("SELECT GPreis from GETR WHERE GName = 'Wasser'")[0][0]
    water_price = formatprices.format_prices(water_data)

    beer_data = dbconnector.sql("SELECT GPreis from GETR WHERE GName = 'Bier'")[0][0]
    beer_price = formatprices.format_prices(beer_data)

    soft_data = dbconnector.sql("SELECT GPreis from GETR WHERE GName = 'Softdrink'")[0][0]
    soft_price = formatprices.format_prices(soft_data)

    icetea_data = dbconnector.sql("SELECT GPreis from GETR WHERE GName = 'Eistee'")[0][0]
    icetea_price = formatprices.format_prices(icetea_data)

    return render_template("drinkselector.html", beer_price=beer_price, water_price=water_price,
                           icetea_price=icetea_price, soft_price=soft_price)


@app.route("/dbtest")
def dbtest():
    sql_statement = f"SELECT MAX(ID) FROM ID "
    return dbconnector.sql(sql_statement)


if __name__ == '__main__':
    app.run(debug=True, host="0.0.0.0")
