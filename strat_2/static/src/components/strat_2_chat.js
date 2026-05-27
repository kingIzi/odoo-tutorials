/** @odoo-module */
import { Component, useState, useRef, onPatched } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class Strat2Chat extends Component {
    static template = "strat_2.ChatWidget";

    setup() {
        this.state = useState({
            isOpen: false,
            messages: [],
            inputText: "",
            isLoading: false,
        });
        this.orm = useService("orm");
        this.messageAreaRef = useRef("messageArea");

        onPatched(() => {
            const el = this.messageAreaRef.el;
            if (el) {
                el.querySelectorAll(".strat2-bot-raw").forEach((node) => {
                    node.innerHTML = node.dataset.html;
                    node.classList.remove("strat2-bot-raw");
                });
                el.scrollTop = el.scrollHeight;
            }
        });
    }

    async toggleChat() {
        this.state.isOpen = !this.state.isOpen;
        if (this.state.isOpen && !this.state.messages.length) {
            await this.loadMessages();
        }
    }

    async loadMessages() {
        try {
            const messages = await this.orm.call(
                "strat2.message",
                "get_conversation",
                [],
            );
            this.state.messages = messages;
        } catch (e) {
            console.error("Strat 2: failed to load messages", e);
        }
    }

    async sendMessage() {
        const text = this.state.inputText.trim();
        if (!text || this.state.isLoading) return;

        this.state.messages.push({ is_user: true, message: text });
        this.state.inputText = "";
        this.state.isLoading = true;

        try {
            const result = await this.orm.call(
                "strat2.message",
                "send_and_respond",
                [],
                {
                    message: text,
                },
            );

            const responseText =
                typeof result === "string" ? result : result.response || "";

            this.state.messages.push({ is_user: false, message: responseText });
        } catch (error) {
            this.state.messages.push({
                is_user: false,
                message: "Sorry, something went wrong. Please try again.",
            });
        }

        this.state.isLoading = false;
    }

    async clearChat() {
        try {
            await this.orm.call("strat2.message", "clear_conversation", []);
            this.state.messages = [];
        } catch (e) {
            console.error("Strat 2: failed to clear messages", e);
        }
    }

    quickAction(text) {
        this.state.inputText = text;
        this.sendMessage();
    }

    onKeydown(ev) {
        if (ev.key === "Enter" && !ev.shiftKey) {
            ev.preventDefault();
            this.sendMessage();
        }
    }

    // -- Markdown renderer ------------------------------------------------

    renderMarkdown(text) {
        if (!text) return "";

        let s = text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
        s = s.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");

        const lines = s.split("\n");
        const blocks = [];
        let cur = { type: "p", lines: [] };

        const flush = () => {
            if (cur.lines.length) blocks.push(cur);
            cur = { type: "p", lines: [] };
        };

        for (const line of lines) {
            const t = line.trim();
            if (t.startsWith("|") && t.endsWith("|")) {
                if (cur.type !== "table") {
                    flush();
                    cur.type = "table";
                }
                cur.lines.push(t);
            } else if (/^[-*]\s+/.test(t)) {
                if (cur.type !== "ul") {
                    flush();
                    cur.type = "ul";
                }
                cur.lines.push(t.replace(/^[-*]\s+/, ""));
            } else if (/^\d+\.\s+/.test(t)) {
                if (cur.type !== "ol") {
                    flush();
                    cur.type = "ol";
                }
                cur.lines.push(t.replace(/^\d+\.\s+/, ""));
            } else if (t === "") {
                flush();
            } else {
                if (cur.type !== "p") {
                    flush();
                }
                cur.lines.push(t);
            }
        }
        flush();

        return blocks
            .map((b) => {
                switch (b.type) {
                    case "table":
                        return this._renderTable(b.lines);
                    case "ul":
                        return this._renderList(b.lines, false);
                    case "ol":
                        return this._renderList(b.lines, true);
                    default:
                        return `<p>${b.lines.join("<br>")}</p>`;
                }
            })
            .join("");
    }

    _renderTable(lines) {
        const isSeparator = (row) => row.replace(/[|\-\s:]/g, "") === "";
        const dataRows = lines.filter((l) => !isSeparator(l));
        if (!dataRows.length) return "";

        const parseCells = (row) =>
            row
                .split("|")
                .slice(1, -1)
                .map((c) => c.trim());

        let html = '<table class="strat2-table">';
        const headerCells = parseCells(dataRows[0]);
        html += "<thead><tr>";
        for (const cell of headerCells) html += `<th>${cell}</th>`;
        html += "</tr></thead>";

        if (dataRows.length > 1) {
            html += "<tbody>";
            for (let i = 1; i < dataRows.length; i++) {
                const cells = parseCells(dataRows[i]);
                html += "<tr>";
                for (const cell of cells) html += `<td>${cell}</td>`;
                html += "</tr>";
            }
            html += "</tbody>";
        }

        html += "</table>";
        return html;
    }

    _renderList(items, ordered) {
        const tag = ordered ? "ol" : "ul";
        const itemsHtml = items.map((i) => `<li>${i}</li>`).join("");
        return `<${tag} class="strat2-list">${itemsHtml}</${tag}>`;
    }
}

registry.category("main_components").add("Strat2Chat", {
    Component: Strat2Chat,
});
