# 🎬 Reels Autopilot: Reels و Shorts تلقائية ومجانية

**فيديو طويل ← Gemini يختار أقوى اللحظات ← مقاطع عمودية مدة كل منها 15 ثانية مع ترجمة متحركة كلمة بكلمة ← نشر على YouTube وInstagram وFacebook وTikTok**

كل الأدوات المستخدمة مجانية: Google Colab وGemini API (الطبقة المجانية) وWhisper وffmpeg وGitHub Actions، إضافة إلى واجهات النشر الرسمية للمنصات.

## ماذا يفعل بالضبط؟

| المرحلة | كيف | مجاني؟ |
|---|---|---|
| اختيار اللحظات | يشاهد Gemini الفيديو (صورة وصوت) ويختار أقوى المقاطع، ثم يكتب لكل مقطع **Hook** وعنواناً ووصفاً وهاشتاقات. وإن لم يتوفر مفتاح Gemini يختار الأداة اللحظات محلياً من ذروات الصوت وتغيّر المشاهد | ✅ |
| القص إلى 9:16 | **Smart crop** يتتبع الوجه ويقص حوله. إن لم يجد وجهاً يضع الفيديو كاملاً فوق خلفية مموّهة منه | ✅ |
| الترجمة على الشاشة | Whisper يحدد توقيت كل كلمة، والكلمة المنطوقة تُلوَّن بالأصفر وتكبر قليلاً. تدعم العربية من اليمين إلى اليسار | ✅ |
| الصوت | توحيد مستوى الصوت على ‎-14 LUFS، وهو المعيار في المنصات | ✅ |
| النشر | واجهات API الرسمية لكل منصة، وتتذكر الأداة ما نُشر فلا يتكرر | ✅ (انظر الحدود) |
| النشر اليدوي | ملف `POST_KIT.md` فيه لكل مقطع نص جاهز للنسخ واللصق لكل منصة | ✅ |

---

## 🚀 الطريقة 1: Google Colab (الأسهل، من المتصفح أو الهاتف)

1. افتح الدفتر:
   **[Reels_Autopilot_Colab.ipynb](https://colab.research.google.com/github/bluesky100090099/free-claude-code/blob/claude/auto-reels-shorts-multiplatform-cy6p5z/reels_autopilot/notebooks/Reels_Autopilot_Colab.ipynb)**
2. من القائمة اختر `Runtime → Change runtime type → T4 GPU`.
3. من أيقونة 🔑 (Secrets) أضف `GEMINI_API_KEY`. احصل عليه مجاناً من <https://aistudio.google.com/apikey>.
4. شغّل الخلايا بالترتيب ▶️، ثم ارفع فيديو أو اختر ملفاً من Drive أو ضع رابطاً.
5. شاهد المعاينة، ثم إما **انشر تلقائياً** أو **نزّل ملف ZIP** وانشر بنفسك.

## 🤖 الطريقة 2: GitHub Actions (نشر يومي تلقائي)

1. في المستودع افتح **Settings → Secrets and variables → Actions** وأضف `GEMINI_API_KEY` ومفاتيح المنصات التي تريدها (القائمة في `.env.example`).
2. افتح تبويب **Actions**. لأن المستودع fork، فعّل الـ workflows إن طُلب منك ذلك.
3. اختر **Reels Autopilot** ثم **Run workflow**، والصق رابط فيديوك.
   - يُصنع المقطع الأول ويُنشر فوراً (يمكن تغيير ذلك من خيار `publish_now`).
   - تُحفظ بقية المقاطع في Release مجاني باسم `reels-queue`.
   - **كل يوم** يُنشر المقطع التالي تلقائياً، والموعد في سطر `cron` داخل الملف.
   - المقاطع متاحة للتنزيل من صفحة الـ run تحت قسم **Artifacts**.
4. تنبيه: الجدولة اليومية لا تعمل إلا بعد دمج ملف `.github/workflows/reels-autopilot.yml` في الفرع الافتراضي (main).

> المستودع عام، لذلك دقائق GitHub Actions مجانية بلا حد.

## 💻 الطريقة 3: على جهازك

```bash
cd reels_autopilot
pip install -r requirements.txt          # ويلزم ffmpeg على الجهاز
cp .env.example .env                     # ثم ضع مفاتيحك
python -m reels doctor                   # يفحص ما هو جاهز
python -m reels make my_video.mp4 -n 5 -d 15 --lang ar
python -m reels publish out/<batch> --next 1    # ينشر مقطعاً واحداً (شغّله يومياً)
python -m reels status out/<batch>
```

---

## 🔑 ربط المنصات (مرة واحدة)

> يكفي `GEMINI_API_KEY` لتبدأ. أي منصة لا تضيف مفاتيحها تُترك للنشر اليدوي من `POST_KIT.md`.

### YouTube Shorts
1. افتح [Google Cloud Console](https://console.cloud.google.com/) وأنشئ مشروعاً، ثم فعّل **YouTube Data API v3**.
2. من **OAuth consent screen** اختر External، وأضف بريدك ضمن *Test users*.
3. من **Credentials** أنشئ OAuth Client ID من نوع *Desktop app*، وانسخ `YT_CLIENT_ID` و`YT_CLIENT_SECRET`.
4. على حاسوبك شغّل `python -m reels auth youtube`، وسيظهر لك `YT_REFRESH_TOKEN`.
   - من الهاتف بدون حاسوب: افتح [OAuth Playground](https://developers.google.com/oauthplayground)، ثم ⚙️ وفعّل *Use your own OAuth credentials*، واختر نطاق `youtube.upload`، ثم *Exchange* وانسخ الـ refresh token.
5. تنبيه: انشر تطبيق الـ consent screen (**In production**)، وإلا انتهت صلاحية الـ token بعد 7 أيام.

### Instagram Reels و Facebook Reels
1. حوّل حساب Instagram إلى **Business** أو **Creator** واربطه بصفحة Facebook.
2. أنشئ تطبيقاً على [developers.facebook.com](https://developers.facebook.com/) من نوع Business. وضع التطوير (Development) يكفي لحساباتك أنت.
3. من [Graph API Explorer](https://developers.facebook.com/tools/explorer/) أنشئ User Token بالصلاحيات التالية:
   `pages_show_list, pages_read_engagement, pages_manage_posts, publish_video, instagram_basic, instagram_content_publish, business_management`
4. شغّل:
   ```bash
   META_APP_ID=... META_APP_SECRET=... python -m reels auth meta --token <التوكن>
   ```
   وستحصل على `FB_PAGE_ID` و`FB_PAGE_TOKEN` و`IG_USER_ID` و`IG_ACCESS_TOKEN`، وهذه **لا تنتهي صلاحيتها**.

### TikTok
1. أنشئ تطبيقاً على [developers.tiktok.com](https://developers.tiktok.com/)، وأضف **Login Kit** و**Content Posting API**، واضبط Redirect URI على رابط https تملكه (يصلح رابط GitHub Pages).
2. ضع `TIKTOK_CLIENT_KEY` و`TIKTOK_CLIENT_SECRET` و`TIKTOK_REDIRECT_URI` في `.env`، ثم شغّل `python -m reels auth tiktok`.
3. الوضع الافتراضي `TIKTOK_MODE=inbox`: يصل الفيديو جاهزاً إلى صندوق الوارد في تطبيق TikTok، وتضغط **نشر** بنقرة واحدة.

---

## ⚠️ بصراحة: حدود المنصات المجانية

| المنصة | الحد |
|---|---|
| **YouTube** | نحو 6 رفعات يومياً بالحصة المجانية. الفيديوهات المرفوعة من مشروع API **غير مُراجَع** تبقى **خاصة (Private)** حتى تجتاز مراجعة Google المجانية ([نموذج المراجعة](https://support.google.com/youtube/contact/yt_api_form)). إلى ذلك الحين تُرفع المقاطع تلقائياً وتجعلها أنت عامة بنقرة. |
| **Instagram** | حساب Business أو Creator فقط، مع حد يومي لعدد المنشورات عبر API (يكفي لمقاطع كثيرة يومياً). |
| **Facebook** | Reels على **صفحة** فقط، لا على الحساب الشخصي. |
| **TikTok** | قبل مراجعة TikTok لتطبيقك: النشر المباشر يكون **خاصاً (SELF_ONLY)** فقط. لهذا وضع `inbox` هو الافتراضي: الفيديو جاهز في تطبيقك وتنشره بنقرة. |
| **Gemini المجاني** | حدود للطلبات في الدقيقة واليوم، وتُعاد المحاولة تلقائياً عند الضغط. الفيديوهات الأطول من 35 دقيقة يُرسل نصها المكتوب بدل الفيديو لتوفير الحصة. |

> 📌 استخدم **فيديوهاتك أنت** أو محتوى لديك حق إعادة نشره. نشر محتوى الآخرين يعرّض حساباتك للحظر.

## 🧩 خيارات مفيدة

| خيار | الوصف |
|---|---|
| `-n 8` | عدد المقاطع |
| `-d 30` | مدة كل مقطع بالثواني (15 افتراضياً) |
| `--crop smart\|blur\|center` | طريقة التحويل إلى العمودي |
| `--picker gemini\|energy` | إجبار طريقة اختيار اللحظات |
| `--lang en` | لغة الترجمة والنصوص |
| `--no-captions` | بدون ترجمة على الشاشة |
| `WHISPER_MODEL=medium` | دقة أعلى للترجمة، ويحتاج GPU |
| `REELS_FONT="Noto Sans Arabic"` | تغيير خط الترجمة |

## 🗂️ البنية

```
reels/
  highlights.py   اختيار اللحظات (Gemini + بديل محلي)
  captions.py     Whisper + ترجمة ASS متحركة
  render.py       قص 9:16 ذكي + ffmpeg
  pipeline.py     make: من فيديو إلى دفعة مقاطع
  publish.py      نشر مع ذاكرة (لا تكرار، وإعادة محاولة حتى 3 مرات)
  publishers/     youtube, instagram, facebook, tiktok
scripts/          قائمة النشر اليومي عبر GitHub Releases
notebooks/        دفتر Google Colab
```

الاختبارات: `pip install pytest && python -m pytest`
