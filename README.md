# Termin-Bot
# Mainz Appointment Notification Bot  

This bot script serves as the foundation for more advanced automation projects I plan to develop in the future. It is a simple but functional project designed to help users automatically get notified when earlier appointment slots become available on the **Mainz Bürgeramt** website.  

---

##  Purpose  

The bot monitors the following section of the Mainz Bürgeramt appointment system:  

**Abteilung Ausländerangelegenheiten → Überträge von Aufenthaltstiteln (neuer Pass)**  
👉 [Mainz Bürgeramt Appointment Page](https://termine-reservieren.de/termine/buergeramt.mainz/?rs)  

Whenever an earlier appointment is released (for example, due to cancellation), the bot automatically sends an **email notification** to the user.

---

##  How It Works  

1. The bot scans all available appointment dates within the next **12 days**.  
2. When it finds an earlier date, it automatically **sends an email** to the configured user address.  
3. Every **12 minutes**, it logs into the website through the user’s Chrome browser and checks for new openings.  
4. Users can adjust both the check interval and search window duration directly in the source code.  

---

## 🧩 Configuration  

The default configuration can be modified in the script:  

| Parameter | Description | Default Value |
|------------|--------------|----------------|
| `CHECK_INTERVAL` | Time between automatic checks | `12 minutes` |
| `SEARCH_RANGE` | Appointment search window | `12 days` |
| `EMAIL_RECEIVER` | Recipient address for notifications | *(user-defined)* |
| `EMAIL_SENDER` | Sender email address (SMTP account) | *(user-defined)* |

---

##  Installation  

### Requirements
- **Python 3.10+**  
- **Playwright** (for browser automation)  
- **smtplib** or compatible email library  

### Setup Steps  

```bash
# 1. Clone this repository
git clone https://github.com/yourusername/mainz-appointment-bot.git
cd mainz-appointment-bot

# 2. Create and activate a virtual environment
python -m venv venv
source venv/bin/activate     # macOS/Linux
venv\Scripts\activate        # Windows

# 3. Install dependencies
pip install playwright
playwright install

# 4. (Optional) Configure email settings in the script
```

---

## 🧠 Example Workflow  

1. The bot starts and launches a headless Chrome instance.  
2. It opens the Mainz Bürgeramt appointment page and navigates to the “Überträge von Aufenthaltstiteln (neuer Pass)” section.  
3. It checks for available appointments within the next 12 days.  
4. If an earlier appointment is found, it sends an automatic email to the configured recipient.  
5. It waits 12 minutes and repeats the process.  

---

## 🛠 Customization  

To change the default values, modify the variables near the top of the script:  

```python
CHECK_INTERVAL = 12 * 60  # 12 minutes in seconds
SEARCH_RANGE = 12         # in days
```

You can also customize:
- Email templates  
- Notification frequency  
- Target appointment categories  

---

## ⚠️ Disclaimer  

This project is for **personal and educational purposes only**.  
It should not be used for large-scale scraping or violating website terms of service.  
Users are responsible for complying with applicable data protection and automation rules.  

---

## 📧 Contact  

For questions, suggestions, or collaboration ideas, feel free to open an issue or reach out via GitHub.  
