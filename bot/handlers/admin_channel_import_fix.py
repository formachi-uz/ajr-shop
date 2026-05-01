from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.handlers.admin_channel_import import ChannelImportState, importer_kb
from bot.keyboards.admin_kb import admin_menu_kb
from bot.middlewares.admin_check import is_admin

router = Router()


async def open_import_mode(message: Message, state: FSMContext):
    await state.set_state(ChannelImportState.waiting_posts)
    await message.answer(
        "📥 <b>Kanaldan mahsulot import qilish yoqildi</b>\n\n"
        "Endi kanalingizdagi mahsulot postlarini shu botga <b>forward</b> qiling.\n"
        "Bot rasm, nom, narx, kategoriya, jamoa/brend va razmerlarni avtomatik o'qib saqlaydi.\n\n"
        "Caption ichida quyidagilar bo'lsa yaxshi ishlaydi:\n"
        "<code>Real Madrid uy formasi 25/26\nNarx: 99 000 so'm\nS:5 M:10 L:8 XL:3</code>\n\n"
        "Tugatish uchun <b>tayyor</b> deb yozing.",
        parse_mode="HTML",
        reply_markup=importer_kb(),
    )


@router.callback_query(F.data == "channel_import_start")
async def start_channel_import_fixed(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return
    await open_import_mode(callback.message, state)
    await callback.answer("Import rejimi yoqildi")


@router.message(F.text.in_({"📥 Kanaldan import", "/importkanal", "/import_channel"}))
async def start_channel_import_text_fixed(message: Message, state: FSMContext):
    if not message.from_user or not is_admin(message.from_user.id):
        await message.answer("⛔ Ruxsat yo'q")
        return
    await open_import_mode(message, state)


@router.callback_query(F.data == "channel_import_stop")
async def stop_channel_import_fixed(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return
    await state.clear()
    await callback.message.answer("✅ Kanaldan import tugatildi.", reply_markup=admin_menu_kb())
    await callback.answer("Tugatildi")
