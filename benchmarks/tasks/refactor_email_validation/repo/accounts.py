def register(user):
    email = user['email']
    local, _, domain = email.partition('@')
    if email.count('@') != 1 or not local or '.' not in domain:
        raise ValueError('invalid email')
    return {**user, 'active': True}


def update_email(user, email):
    local, _, domain = email.partition('@')
    if email.count('@') != 1 or not local or '.' not in domain:
        raise ValueError('invalid email')
    return {**user, 'email': email}
