# add_balance_manually.py - для администратора
import database


def add_balance_manually():
    """Ручное добавление баланса"""
    print("💰 Ручное пополнение баланса")
    print("=" * 40)
    user_id = input("Введите ID пользователя: ")
    try:
        user_id = int(user_id)
    except ValueError:
        print("❌ ID должен быть числом")
        return
    amount = input("Введите сумму для пополнения: ")
    try:
        amount = int(amount)
    except ValueError:
        print("❌ Сумма должна быть числом")
        return
    if amount <= 0:
        print("❌ Сумма должна быть положительной")
        return
    # Добавляем баланс
    database.add_balance(user_id, amount)
    new_balance = database.get_user_balance(user_id)
    print(f"✅ Баланс пользователя {user_id} пополнен на {amount} руб.")
    print(f"💰 Новый баланс: {new_balance} руб.")


if __name__ == '__main__':
    add_balance_manually()
