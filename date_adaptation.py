def date_adaptation(number: int, unit: str):
    forms = {"minute": ["минута", "минуты", "минут"],
             "hour": ["час", "часа", "часов"],
             "day": ["день", "дня", "дней"],
             "week": ["неделя", "недели", "недель"],
             "month": ["месяц", "месяца", "месяцев"],
             "year": ["год", "года", "лет"]}
    if number >= 0:
        if number % 10 == 1 and number % 100 != 11:
            text = forms[unit][0]
        elif 2 <= number % 10 <= 4 and number % 100 not in [12, 13, 14]:
            text = forms[unit][1]
        else:
            text = forms[unit][2]
        return f"{number} {text}"
    elif number == -1:
        return forms[unit][2]
    else:
        return None

seasons = {"January": "Январь",
           "February": "Февраль",
           "March": "Март",
           "April": "Апрель",
           "May": "Май",
           "June": "Июнь",
           "July": "Июль",
           "August": "Август",
           "September": "Сентябрь",
           "October": "Октябрь",
           "November": "Ноябрь",
           "December": "Декабрь"
}

