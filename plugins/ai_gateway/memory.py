import asyncio

class AIMemoryManager:
    RECENT_MESSAGES = 24
    SUMMARY_TRIGGER = 48
    SUMMARY_KEEP_RECENT = 24

    def __init__(self, store):
        self.store = store
        self._locks = {}

    def _lock(self, group_id):
        if group_id not in self._locks:
            self._locks[group_id] = asyncio.Lock()
        return self._locks[group_id]

    async def build_context(self, group_id, system_prompt):
        summary = await self.store.get_summary(group_id)
        recent = await self.store.get_recent(group_id, self.RECENT_MESSAGES)
        messages = [{'role':'system','content':system_prompt}]
        if summary and summary['summary']:
            messages.append({'role':'system','content':'خلاصه حافظه قدیمی گروه:\n' + summary['summary']})
        for row in recent:
            messages.append({'role':row['role'],'content':row['content']})
        return messages

    async def maybe_summarize(self, group_id, gateway):
        async with self._lock(group_id):
            count = await self.store.count(group_id)
            if count <= self.SUMMARY_TRIGGER:
                return
            recent = await self.store.get_recent(group_id, self.SUMMARY_KEEP_RECENT)
            if not recent:
                return
            cutoff = recent[0]['id'] - 1
            old_summary = await self.store.get_summary(group_id)
            after = int(old_summary['through_message_id']) if old_summary else 0
            if cutoff <= after:
                return
            rows = await self.store.get_unsummarized(group_id, after, cutoff, 24)
            if not rows:
                return
            transcript = '\n'.join(('کاربر' if r['role']=='user' else 'بوبی') + ': ' + r['content'] for r in rows)
            previous = old_summary['summary'] if old_summary else 'هیچ حافظه قدیمی وجود ندارد.'
            prompt = [
                {'role':'system','content':'حافظه گروه را خلاصه کن. نام اعضا، روابط، ترجیحات و واقعیت های مهم را حفظ کن و فقط خلاصه را برگردان.'},
                {'role':'user','content':'حافظه قبلی:\n'+previous+'\n\nگفتگو:\n'+transcript},
            ]
            try:
                summary = await gateway.chat(prompt, timeout=45, temperature=0)
            except Exception as exc:
                print(f'⚠️ خطا در خلاصه سازی حافظه گروه {group_id}: {exc}')
                return
            await self.store.save_summary(group_id, summary, rows[-1]['id'])
            await self.store.delete_through(group_id, rows[-1]['id'])

    @staticmethod
    def format_user_message(name, user_id, text):
        return f'[کاربر: {name} | شناسه: {user_id}]\n{text}'
