import os
from datetime import datetime

from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, CallbackContext, MessageHandler, Filters
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from database import User, Note, Base
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL не задан в .env файле")

token = os.getenv("TOKEN")
if not token:
    raise ValueError("TOKEN не задан в .env файле")

engine = create_engine(DATABASE_URL, echo=True)
Session = sessionmaker(bind=engine)

class NoteBot:
    def __init__(self):
        self.updater = Updater(token=token, use_context=True)
        self.dispatcher = self.updater.dispatcher
        self.job_queue = self.updater.job_queue
        self.user_states = {}

        self.add_handlers()
        self.create_tables()

    def create_tables(self):
        Base.metadata.create_all(engine)

    def add_handlers(self):
        self.dispatcher.add_handler(CommandHandler("start", self.start))
        self.dispatcher.add_handler(CommandHandler("create", self.create_note_prompt))
        self.dispatcher.add_handler(CommandHandler("update", self.update_note_prompt))
        self.dispatcher.add_handler(CommandHandler("delete", self.delete_note_prompt))
        self.dispatcher.add_handler(CommandHandler("remind", self.remind_note_prompt))
        self.dispatcher.add_handler(CallbackQueryHandler(self.handle_button_click))
        self.dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, self.handle_message))

    def get_main_keyboard(self):
        buttons = [
            ["Create Note", "View Notes"],
            ["Update Note", "Delete Note"],
            ["Set Reminder"]
        ]
        return ReplyKeyboardMarkup(buttons, resize_keyboard=True, one_time_keyboard=False)

    def start(self, update: Update, context: CallbackContext):
        user_id = update.message.from_user.id
        username = update.message.from_user.username

        with Session() as session:
            user = session.query(User).filter_by(user_id=user_id).first()

            if not user:
                user = User(user_id=user_id, username=username)
                session.add(user)
                session.commit()

        reply_markup = self.get_main_keyboard()
        update.message.reply_text(
            f"Привет, {username}! Выберите действие:",
            reply_markup=reply_markup
        )

    def remind_note_prompt(self, update: Update, context: CallbackContext):
        user_id = update.callback_query.from_user.id if update.callback_query else update.message.from_user.id
        self.user_states[user_id] = "waiting_for_note_id_for_reminder"
        update.effective_message.reply_text("Введите ID заметки, для которой хотите установить напоминание.")

    def create_note_prompt(self, update: Update, context: CallbackContext):
        user_id = update.message.from_user.id
        self.user_states[user_id] = "waiting_for_note_title"
        update.message.reply_text("Введите заголовок заметки.")

    def update_note_prompt(self, update: Update, context: CallbackContext):
        user_id = update.message.from_user.id
        self.user_states[user_id] = "waiting_for_note_id"
        update.message.reply_text("Введите ID заметки, которую вы хотите обновить.")

    def set_reminder(self, user_id, note_id, remind_time):
        with Session() as session:
            note = session.query(Note).filter_by(note_id=note_id, user_id=user_id).first()
            if not note:
                return False

            time_delta = (remind_time - datetime.now()).total_seconds()
            if time_delta <= 0:
                return False

            self.job_queue.run_once(self.send_reminder, time_delta, context=(user_id, note_id))
            print(f"Напоминание установлено для пользователя {user_id} на {remind_time}")
            return True

    def send_reminder(self, context: CallbackContext):
        user_id, note_id = context.job.context
        with Session() as session:
            note = session.query(Note).filter_by(note_id=note_id, user_id=user_id).first()
            if note:
                context.bot.send_message(
                    chat_id=user_id,
                    text=f"Напоминание о заметке:\n\nЗаголовок: {note.title}\nСодержание: {note.content}"
                )
                print(f"Напоминание отправлено пользователю {user_id} о заметке {note_id}.")
            else:
                print(f"Напоминание не удалось: заметка {note_id} не найдена для пользователя {user_id}.")

    def delete_note_prompt(self, update: Update, context: CallbackContext):
        user_id = update.message.from_user.id
        self.user_states[user_id] = "waiting_for_note_id_for_delete"
        update.message.reply_text("Введите ID заметки, которую вы хотите удалить.")

    def delete_note_by_id(self, user_id, note_id):
        with Session() as session:
            note = session.query(Note).filter_by(note_id=note_id, user_id=user_id).first()
            if not note:
                return False
            session.delete(note)
            session.commit()
            return True

    def handle_message(self, update: Update, context: CallbackContext):
        user_id = update.message.from_user.id
        text = update.message.text

        if user_id in self.user_states:
            state = self.user_states[user_id]

            if state == "waiting_for_note_title":
                context.user_data["note_title"] = text
                self.user_states[user_id] = "waiting_for_note_content"
                update.message.reply_text("Введите содержание заметки.")
                return

            elif state == "waiting_for_note_content":
                context.user_data["note_content"] = text
                self.user_states[user_id] = "waiting_for_note_date"
                update.message.reply_text("Введите дату и время заметки в формате ДД.ММ.ГГГГ ЧЧ:ММ.")
                return

            elif state == "waiting_for_note_date":
                try:
                    note_date = datetime.strptime(text, "%d.%m.%Y %H:%M")
                    context.user_data["note_date"] = note_date

                    with Session() as session:
                        note = Note(
                            title=context.user_data["note_title"],
                            content=context.user_data["note_content"],
                            created_at=context.user_data["note_date"],
                            user_id=user_id,
                        )
                        session.add(note)
                        session.commit()

                    update.message.reply_text(
                        "Заметка успешно создана!"
                        f"\nЗаголовок: {context.user_data['note_title']}"
                        f"\nСодержание: {context.user_data['note_content']}"
                        f"\nДата: {context.user_data['note_date'].strftime('%d.%m.%Y %H:%M')}"
                    )

                    self.reset_user_state(user_id, context)
                except ValueError:
                    update.message.reply_text("Неверный формат даты. Введите в формате ДД.ММ.ГГГГ ЧЧ:ММ.")
                return

            elif state == "waiting_for_note_id":
                try:
                    note_id = int(text)
                    with Session() as session:
                        note = session.query(Note).filter_by(note_id=note_id, user_id=user_id).first()

                        if not note:
                            update.message.reply_text("Заметка с таким ID не найдена. Попробуйте снова.")
                            return

                        context.user_data["note"] = note
                        self.user_states[user_id] = "waiting_for_update_field"
                        update.message.reply_text(
                            "Что вы хотите обновить? Введите одно из: title, content, date."
                        )
                except ValueError:
                    update.message.reply_text("ID должен быть числом. Попробуйте снова.")
                return

            elif state == "waiting_for_update_field":
                field = text.lower()
                if field in ["title", "content", "date"]:
                    context.user_data["update_field"] = field
                    self.user_states[user_id] = f"waiting_for_new_{field}"
                    update.message.reply_text(f"Введите новое значение для {field}.")
                else:
                    update.message.reply_text("Некорректный выбор. Введите одно из: title, content, date.")
                return

            elif state == "waiting_for_new_title":
                new_title = text
                with Session() as session:
                    note = context.user_data.get("note")
                    note.title = new_title
                    session.merge(note)
                    session.commit()
                update.message.reply_text(f"Заголовок заметки обновлен на '{new_title}'.")
                self.reset_user_state(user_id, context)
                return

            elif state == "waiting_for_new_content":
                new_content = text
                with Session() as session:
                    note = context.user_data.get("note")
                    note.content = new_content
                    session.merge(note)
                    session.commit()
                update.message.reply_text("Содержание заметки обновлено.")
                self.reset_user_state(user_id, context)
                return

            elif state == "waiting_for_note_id_for_reminder":
                try:
                    note_id = int(text)
                    with Session() as session:
                        note = session.query(Note).filter_by(note_id=note_id, user_id=user_id).first()
                        if not note:
                            update.message.reply_text("Заметка с таким ID не найдена. Попробуйте снова.")
                            return

                        context.user_data["note"] = note
                        self.user_states[user_id] = "waiting_for_remind_time"
                        update.message.reply_text(
                            "Введите время напоминания в формате ДД.ММ.ГГГГ ЧЧ:ММ."
                        )
                except ValueError:
                    update.message.reply_text("ID должен быть числом. Попробуйте снова.")
                return

            elif state == "waiting_for_remind_time":
                try:
                    remind_time = datetime.strptime(text, "%d.%m.%Y %H:%M")
                    now = datetime.now()
                    if remind_time < now:
                        update.message.reply_text("Время напоминания не может быть в прошлом. Попробуйте снова.")
                        return

                    note = context.user_data.get("note")
                    if self.set_reminder(user_id, note.note_id, remind_time):
                        update.message.reply_text(
                            f"Напоминание для заметки '{note.title}' установлено на {remind_time.strftime('%d.%m.%Y %H:%M')}."
                        )
                        self.reset_user_state(user_id, context)
                    else:
                        update.message.reply_text("Не удалось установить напоминание. Попробуйте снова.")
                except ValueError:
                    update.message.reply_text("Неверный формат даты. Введите в формате ДД.ММ.ГГГГ ЧЧ:ММ.")
                return

            elif state == "waiting_for_new_date":
                try:
                    new_date = datetime.strptime(text, "%d.%m.%Y %H:%M")
                    with Session() as session:
                        note = context.user_data.get("note")
                        note.created_at = new_date
                        session.merge(note)
                        session.commit()
                    update.message.reply_text(
                        f"Дата и время заметки обновлены на {new_date.strftime('%d.%m.%Y %H:%M')}."
                    )
                    self.reset_user_state(user_id, context)
                except ValueError:
                    update.message.reply_text(
                        "Неверный формат даты. Введите в формате ДД.ММ.ГГГГ ЧЧ:ММ."
                    )
                return
            elif state == "waiting_for_note_id_for_delete":
                try:
                    note_id = int(text)
                    if self.delete_note_by_id(user_id, note_id):
                        update.message.reply_text(f"Заметка с ID {note_id} успешно удалена.")
                    else:
                        update.message.reply_text("Заметка с таким ID не найдена. Попробуйте снова.")
                    self.reset_user_state(user_id, context)
                except ValueError:
                    update.message.reply_text("ID должен быть числом. Попробуйте снова.")
                return

        if text == "Create Note":
            self.create_note_prompt(update, context)
        elif text == "Set Reminder":
            self.remind_note_prompt(update, context)
        elif text == "Create Note":
            self.create_note_prompt(update, context)
        elif text == "View Notes":
            self.view_notes(update, context)
        elif text == "Update Note":
            self.update_note_prompt(update, context)
        elif text == "Delete Note":
            self.delete_note_prompt(update, context)
        else:
            update.message.reply_text(
                "Я не понимаю. Выберите действие на клавиатуре или используйте команду.",
                reply_markup=self.get_main_keyboard()
            )

    def reset_user_state(self, user_id, context):
        if user_id in self.user_states:
            del self.user_states[user_id]
        context.user_data.clear()

    def handle_button_click(self, update: Update, context: CallbackContext):
        query = update.callback_query

        if query.data == "create_note":
            self.create_note_prompt(query, context)
        elif query.data == "view_notes":
            self.view_notes(query, context)
        elif query.data == "update_note":
            self.update_note_prompt(query, context)
        elif query.data == "delete_note":
            self.delete_note_prompt(query, context)
        elif query.data == "set_reminder":
            self.remind_note_prompt(query, context)
        else:
            query.edit_message_text("Неизвестное действие.")

    def view_notes(self, update: Update, context: CallbackContext):
        if update.callback_query:
            user_id = update.callback_query.from_user.id
        elif update.message:
            user_id = update.message.from_user.id
        else:
            return update.message.reply_text("Не удалось определить пользователя.")

        with Session() as session:
            user = session.query(User).filter_by(user_id=user_id).first()

            if not user or not user.notes:
                if update.callback_query:
                    update.callback_query.edit_message_text("У вас нет заметок.")
                else:
                    update.message.reply_text("У вас нет заметок.")
                return

            now = datetime.now()
            active_notes = (
                session.query(Note)
                .filter(Note.user_id == user_id, Note.created_at >= now)
                .order_by(Note.created_at)
                .all()
            )

            if not active_notes:
                if update.callback_query:
                    update.callback_query.edit_message_text("У вас нет актуальных заметок.")
                else:
                    update.message.reply_text("У вас нет актуальных заметок.")
                return

            message = "\n\n".join(
                [
                    f"ID: {note.note_id}\nЗаголовок: {note.title}\nСодержание: {note.content}\n"
                    f"Дата: {note.created_at.strftime('%d.%m.%Y %H:%M')}"
                    for note in active_notes
                ]
            )

            if update.callback_query:
                update.callback_query.edit_message_text(message)
            else:
                update.message.reply_text(message)

    def run(self):
        self.updater.start_polling()
        self.updater.idle()

if __name__ == "__main__":
    bot = NoteBot()
    bot.run()
