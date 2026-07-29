import tkinter as tk
from tkinter import ttk, messagebox


TEXT = {
    "app_title": "eBay \u5229\u76ca\u8a08\u7b97\u30c4\u30fc\u30eb",
    "purchase_price": "\u4ed5\u5165\u308c\u4fa1\u683c\uff08\u5186\uff09",
    "sale_price_usd": "\u8ca9\u58f2\u4fa1\u683c\uff08USD\uff09",
    "shipping_yen": "\u9001\u6599\uff08\u5186\uff09",
    "exchange_rate": "\u70ba\u66ff\u30ec\u30fc\u30c8\uff08\u5186/USD\uff09",
    "fee_rate": "eBay\u624b\u6570\u6599\u7387\uff08%\uff09",
    "calculate": "\u8a08\u7b97",
    "clear": "\u30af\u30ea\u30a2",
    "sales_yen": "\u5186\u63db\u7b97\u58f2\u4e0a",
    "ebay_fee": "eBay\u624b\u6570\u6599",
    "profit_yen": "\u5229\u76ca\uff08\u5186\uff09",
    "profit_margin": "\u5229\u76ca\u7387",
    "note": "\u5229\u76ca\u7387 = \u5229\u76ca \u00f7 \u5186\u63db\u7b97\u58f2\u4e0a",
    "input_error": "\u5165\u529b\u30a8\u30e9\u30fc",
    "positive_sale_price": "\u8ca9\u58f2\u4fa1\u683c\uff08USD\uff09\u306f0\u3088\u308a\u5927\u304d\u3044\u6570\u5024\u3092\u5165\u529b\u3057\u3066\u304f\u3060\u3055\u3044\u3002",
    "enter_value": "{label}\u3092\u5165\u529b\u3057\u3066\u304f\u3060\u3055\u3044\u3002",
    "numeric_value": "{label}\u306f\u6570\u5024\u3067\u5165\u529b\u3057\u3066\u304f\u3060\u3055\u3044\u3002",
    "non_negative": "{label}\u306f0\u4ee5\u4e0a\u306e\u6570\u5024\u3092\u5165\u529b\u3057\u3066\u304f\u3060\u3055\u3044\u3002",
    "yen": "\u5186",
}


class EbayProfitCalculator(ttk.Frame):
    def __init__(self, master: tk.Tk) -> None:
        super().__init__(master, padding=20)
        self.master = master
        self.entries = {}

        self.profit_var = tk.StringVar(value="-")
        self.margin_var = tk.StringVar(value="-")
        self.sales_yen_var = tk.StringVar(value="-")
        self.fee_var = tk.StringVar(value="-")

        self._build_ui()

    def _build_ui(self) -> None:
        self.master.title(TEXT["app_title"])
        self.master.geometry("430x430")
        self.master.minsize(390, 410)

        self.grid(sticky="nsew")
        self.master.columnconfigure(0, weight=1)
        self.master.rowconfigure(0, weight=1)
        self.columnconfigure(1, weight=1)

        title = ttk.Label(self, text=TEXT["app_title"], font=("", 16, "bold"))
        title.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 16))

        fields = [
            ("purchase_price", TEXT["purchase_price"]),
            ("sale_price_usd", TEXT["sale_price_usd"]),
            ("shipping_yen", TEXT["shipping_yen"]),
            ("exchange_rate", TEXT["exchange_rate"]),
            ("fee_rate", TEXT["fee_rate"]),
        ]

        for row, (key, label_text) in enumerate(fields, start=1):
            label = ttk.Label(self, text=label_text)
            label.grid(row=row, column=0, sticky="w", pady=6)

            entry = ttk.Entry(self, justify="right")
            entry.grid(row=row, column=1, sticky="ew", pady=6, padx=(12, 0))
            entry.bind("<Return>", lambda _event: self.calculate())
            self.entries[key] = entry

        defaults = {
            "purchase_price": "1000",
            "sale_price_usd": "20",
            "shipping_yen": "800",
            "exchange_rate": "150",
            "fee_rate": "13.25",
        }
        for key, value in defaults.items():
            self.entries[key].insert(0, value)

        button_frame = ttk.Frame(self)
        button_frame.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(16, 18))
        button_frame.columnconfigure(0, weight=1)
        button_frame.columnconfigure(1, weight=1)

        calculate_button = ttk.Button(button_frame, text=TEXT["calculate"], command=self.calculate)
        calculate_button.grid(row=0, column=0, sticky="ew", padx=(0, 6))

        clear_button = ttk.Button(button_frame, text=TEXT["clear"], command=self.clear)
        clear_button.grid(row=0, column=1, sticky="ew", padx=(6, 0))

        separator = ttk.Separator(self)
        separator.grid(row=7, column=0, columnspan=2, sticky="ew", pady=(0, 14))

        result_rows = [
            (TEXT["sales_yen"], self.sales_yen_var),
            (TEXT["ebay_fee"], self.fee_var),
            (TEXT["profit_yen"], self.profit_var),
            (TEXT["profit_margin"], self.margin_var),
        ]

        for row, (label_text, variable) in enumerate(result_rows, start=8):
            label = ttk.Label(self, text=label_text)
            label.grid(row=row, column=0, sticky="w", pady=5)

            value = ttk.Label(self, textvariable=variable, anchor="e", font=("", 11, "bold"))
            value.grid(row=row, column=1, sticky="ew", pady=5, padx=(12, 0))

        note = ttk.Label(self, text=TEXT["note"], foreground="#555555")
        note.grid(row=12, column=0, columnspan=2, sticky="w", pady=(14, 0))

        self.entries["purchase_price"].focus()

    def calculate(self) -> None:
        try:
            purchase_price = self._read_float("purchase_price")
            sale_price_usd = self._read_float("sale_price_usd")
            shipping_yen = self._read_float("shipping_yen")
            exchange_rate = self._read_float("exchange_rate")
            fee_rate = self._read_float("fee_rate")
        except ValueError as exc:
            messagebox.showerror(TEXT["input_error"], str(exc))
            return

        if sale_price_usd <= 0:
            messagebox.showerror(TEXT["input_error"], TEXT["positive_sale_price"])
            return

        sales_yen = sale_price_usd * exchange_rate
        ebay_fee = sales_yen * (fee_rate / 100)
        profit = sales_yen - purchase_price - shipping_yen - ebay_fee
        profit_margin = (profit / sales_yen) * 100

        self.sales_yen_var.set(f"{sales_yen:,.0f} {TEXT['yen']}")
        self.fee_var.set(f"{ebay_fee:,.0f} {TEXT['yen']}")
        self.profit_var.set(f"{profit:,.0f} {TEXT['yen']}")
        self.margin_var.set(f"{profit_margin:.2f} %")

    def clear(self) -> None:
        for entry in self.entries.values():
            entry.delete(0, tk.END)

        self.sales_yen_var.set("-")
        self.fee_var.set("-")
        self.profit_var.set("-")
        self.margin_var.set("-")
        self.entries["purchase_price"].focus()

    def _read_float(self, key: str) -> float:
        value = self.entries[key].get().strip().replace(",", "")

        if not value:
            raise ValueError(TEXT["enter_value"].format(label=TEXT[key]))

        try:
            number = float(value)
        except ValueError as exc:
            raise ValueError(TEXT["numeric_value"].format(label=TEXT[key])) from exc

        if number < 0:
            raise ValueError(TEXT["non_negative"].format(label=TEXT[key]))

        return number


def main() -> None:
    root = tk.Tk()
    ttk.Style().theme_use("clam")
    EbayProfitCalculator(root)
    root.mainloop()


if __name__ == "__main__":
    main()
