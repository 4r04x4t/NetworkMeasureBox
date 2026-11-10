# NMHH Szélessáv.net measuring box and NetworkMeasureBox – a comparison

This page compares the official measuring box of the Hungarian regulator NMHH (Szélessáv Program, "SZÉP") with NetworkMeasureBox (NMB), for anyone who wants to measure their own internet line. Hungarian version: [NMHH_SZELESSAVNET_OSSZEHASONLITAS.hu.md](NMHH_SZELESSAVNET_OSSZEHASONLITAS.hu.md).

**Sources and marks.** Every statement says where it comes from:

- **[Contract]** – NMHH's sample administrative contract for taking part in the Szélessáv Program (2018, with annex 1), published on the application page;
- **[Application page]** – <https://szelessav.net/merodoboz-igenylese> (read on 10 November 2026);
- **[Experience]** – the project owner's own experience with the box; not confirmed by an official source;
- **[NMB]** – NetworkMeasureBox's own documentation and tests (`README.md`, `docs/TESTING.md`).

This is neither legal advice nor an official position. NMHH's current contract and website always decide. NMHH's system is an official one (its data can be used in regulatory procedures and for the national statistics); NMB does not replace that role.

---

## 1. What is the problem with the current NMHH box?

### Hungary only
- The system "was built to check the internet providers present in Hungary", and "measurements cannot be started from abroad". **[Contract, annex 1, point 5]**
- Only "natural persons with a residence in Hungary" can take part. **[Contract]**

### Not for everyone
- Conditions: over 18, residence in Hungary, own broadband subscription or the subscriber's consent; the property owner's consent if someone else owns it. **[Contract]**
- NMHH accepts or refuses each application by the number of applicants and the geographic, provider and package distribution of existing measuring points; it may refuse an address that would skew the sample. **[Contract; Application page]**
- The application form appears only after at least five measurements with NMHH's software tools. **[Application page]**
- Lines above 1000 Mb/s should not apply for now. **[Application page]**

### Free, but it has a price: running it, and giving it back
- The box is **owned by the Hungarian State**; NMHH exercises the owner's rights. The participant gets a free right of use, **for an indefinite period**. **[Contract]**
- The participant must **set it up within 3 days** and run it as intended, **cannot ask for payment or for the running costs** (such as electricity), and runs it **at their own responsibility**. **[Contract]**
- The participant is **liable for damage** from improper use, must report a fault within 3 working days and any change of data, provider, package or address **within 8 days**. **[Contract]**
- When the contract ends, the box must be **returned in working order**, or its value or the damage paid. **[Contract]**
- Either side may end the contract with 15 days' notice; **NMHH may also end it when the line is good and stable** (three months of measurements at least 90% of the guaranteed speed and at least 90% availability). **[Contract]**

### Results go to NMHH only, and only NMHH's servers are used
- Measurements use "a domestically developed system equivalent to the internationally accepted Ookla system", with the central server at BIX (Budapest Internet Exchange). **[Contract, annex 1, point 2]** No other engine (Ookla Speedtest, RTR-NetTest, Cloudflare, iPerf3) and no other server can be chosen. **[Contract; Experience]**
- Results are on the szelessav.net portal, kept individually for **90 days**, then only averaged and aggregated. The participant's own tests started on the box are shown **only on the box's web page** and are not stored by the system. **[Contract, annex 1, point 4]**
- Own tests are less precise (one average-size transfer). **[Contract, annex 1, point 5]**

### The software is closed and must not be touched
- The participant must not open the device, change its software or influence its operation; changing the software, or even trying to, is a reason for **immediate termination**. **[Contract]**
- Source code and API are not public. **[Experience]**

### Other limits
- **Provider name mismatch:** if NMHH's records show another provider than the one actually serving the line, a warning may follow. Example: "Digi Hungary" recorded while One provides the service on the 2Connect network. **[Experience]** A change of provider or package must be reported within 8 days. **[Contract]**
- **Basic web interface** on the box. **[Experience]**
- **At most about 1 Gbit/s, no link aggregation.** **[Experience]** The application page focuses on lines below 1000 Mb/s. **[Application page]**

## 2. Advantages of the NMHH box

- Hardware: a re-programmable Linksys WRT3200ACM router with its own custom firmware; changing it breaks the contract. **[Experience; the ban on changes: Contract]**
- Stable software. **[Experience]**
- Official measurements that can be used in NMHH's procedures. **[Contract]** NMB's SLA result is its own evaluation, not an official decision. **[NMB]**
- Clear graphs on the szelessav.net site and CSV export. **[Experience]** Results are available in printable form. **[Contract]**
- Measures only when the line is idle, independent of the user's computer. **[Contract; Application page]**
- LAN passthrough: placed between the access point and the user's devices. **[Application page]** Passes the traffic through. **[Experience]**
- Measuring engine developed at BME (Budapest University of Technology and Economics). **[Experience]** The contract speaks of a "domestically developed" system. **[Contract]**

### Not tried, may not exist
- PPPoE and router functions on the box. **[Experience: not tried]**

## 3. Advantages of NetworkMeasureBox

| Topic | NetworkMeasureBox | Status |
|---|---|---|
| Ownership | 100% your own device; no contract, deadline or return | **[NMB]** |
| Engines | Several in one place: Ookla Speedtest, Cloudflare, Fast.com (Netflix), RTR-NetTest (Open-RMBT), iPerf3; choose which run in the scheduled mixed run | tested live **[NMB, TESTING]** |
| Servers | Domestic and international, plus content providers and CDNs (Cloudflare, Fast.com/Netflix); a wider choice with Ookla and iPerf3 | **[NMB]** |
| Frequency | Adjustable schedule, a separate interval per engine (Ookla at most hourly, and only after its terms are accepted) | **[NMB]** |
| Where results show | Locally (Web UI, Telegram, CLI, SLA dossier, CSV); Ookla and RTR results also go into their own systems, so they count in international comparisons | **[NMB]** |
| Country | Not tied to Hungary; the native build is planned to show only what applies in its country | **[NMB; planned: DEPYTHONIZATION_ROADMAP point 9]** |
| Modes | Standalone, router mode (DHCP, NAT, PPPoE, IPv6, port forwarding), transparent mode (LAN passthrough, bridge), automatic mode | router mode on PPPoE and standalone tested live; passthrough and automatic mode in part **[NMB, TESTING]** |
| Mobile internet | Measured, and usable through USB tethering (phone, mobile hotspot, modem) | tested live **[NMB, TESTING]** |
| Wi-Fi | Client and access point | 2.4 and 5 GHz tested live **[NMB, TESTING]** |
| Speed | One gigabit port on the Raspberry Pi 4; above 1 Gbit/s depending on the supported device and the development stage; link aggregation is in the software | above 1 Gbit/s **planned**, not measured live **[NMB]** |
| Control | Web UI, Telegram alerts and commands, CLI (`nmb-cli`) | **[NMB]** |
| Source | Open source (MIT), free to change | **[NMB]** |
| With an AI assistant | Open code and plain-text settings make it easier to run, debug and extend with an LLM (for example Claude Code) | **[NMB]** |

## 4. Which one when?

- **NMHH's box** if you want official measurements and accept the terms (residence in Hungary, NMHH's decision, running it continuously, reporting changes, returning it, no changes to its software).
- **NetworkMeasureBox** if you want your own, freely usable device with several engines and servers, an adjustable schedule, router and mobile-internet abilities, in any country.
- **Both together:** NMB does not replace the official measurement, but its own results complement it.

---

*Written on 10 November 2026; sources as read that day. The sample contract is dated 2018; if NMHH has changed it since, the current text applies.*
