def validate_email(email):
    local, _, domain = email.partition('@')
    return email.count('@') == 1 and bool(local) and '.' in domain


def register(user):
    if not validate_email(user['email']):
        raise ValueError('invalid email')
    return {**user, 'active': True}


def update_email(user, email):
    if not validate_email(email):
        raise ValueError('invalid email')
    return {**user, 'email': email}
