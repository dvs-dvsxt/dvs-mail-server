# ✉️ Mail Server — CLI Email Server

> A **command-line email server** (pure CLI) with SMTP receive/send support, mailbox management, and server control.

**Mail Server** is a Python CLI-based email server. It can receive email via SMTP (with configurable ports), send email, list/view received & sent messages, and manage SMTP server instances — all from the command line.

---

## ✨ Features

| Feature | Description |
|---------|-------------|
| 📥 **Receive Email** | SMTP server with configurable ports (25 / 587 / 465) |
| 📤 **Send Email** | Send plain-text or multipart emails |
| 📋 **Mailbox List** | List & view received / sent emails |
| 📎 **Download** | Get email message content |
| 🖥️ **Multi-Server** | Start / stop multiple SMTP servers |
| 🔐 **Admin Auth** | Password-protected server management |
| 🗂️ **Persistent Storage** | Emails saved to JSON data file |

---

## 🚀 Quick Start

### Prerequisites
- Python 3.8+
- `dnspython`, `chardet` (for DNS & encoding)
- Root/admin privileges (to bind SMTP ports)

### Run

```bash
python mail.py
```

### CLI Commands

| Command | Description |
|---------|-------------|
| `help` | Show help / available commands |
| `init` | Initialize configuration (domain, admin password) |
| `start` | Start SMTP server |
| `stop` | Stop SMTP server |
| `status` | Show server status |
| `send` | Send an email |
| `list` | List emails |
| `view` | View an email |
| `download` | Download an email |
| `clear` | Clear mailbox |
| `exit` | Exit the program |

---

## 📁 Project Structure

```
mail/
├── mail.py        # CLI email server (main program)
└── README.md      # This document
```

> At runtime creates: `mail_config.json` (config) & `email_data.json` (email storage)

---

## 📄 License

This project is licensed under the **MIT License**. See [LICENSE](LICENSE) for details.

---

## ⚠️ Security Note

> Running an SMTP server on standard ports (25/587/465) requires **administrator/root** privileges. Be careful with open relays — configure authentication and restrict access. This project is for learning/reference.
