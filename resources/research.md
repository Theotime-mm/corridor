# Research notes (Nov 2026)

What already exists, what the field actually does, and TAK access facts. For positioning and the
pitch. Each line is a summary; check the source before quoting it on a slide.

## Ukraine: DELTA / Mission Control

- Mission Control (DELTA module): crews plan missions, responsibility zones, routes, real-time
  task coordination. [MoD](https://mod.gov.ua/en/news/kateryna-chernohorenko-the-mission-control-module-is-now-accessible-to-all-delta-users)
- Described as coordinating missions "with electronic warfare and air defense units".
  [United24](https://united24media.com/latest-news/ukraines-delta-combat-system-may-be-exported-to-nato-ally-defense-official-says-7971)
- Gives UAV, EW and air-defence personnel visibility of which friendly drones operate in a sector.
  [The Defender](https://thedefender.media/en/2026/01/mission-control-launch/)
- Frequency management: queue of UAV departures per area.
  [Militarnyi](https://militarnyi.com/en/news/ukrainian-uav-units-are-actively-mastering-the-mission-control-module/)
- Routes are defined in advance taking EW risk into account.
  [Root-Nation](https://root-nation.com/en/aeronaut-en/aeronaut-articles-en/en-mission-control-ukraine/)
- Scale: 3M+ strike missions logged March to Oct 2026.
  [MoD](https://mod.gov.ua/en/news/drone-warfare-in-ukraine-what-does-delta-record)
- Not found publicly: a friendly-jammer coverage map, automatic routing, routing against the
  jammer cut schedule. Likely partly classified, so say "no public sign of", not "does not".

## The problem in the field (pitch evidence)

- Pilots reserve corridors past friendly jammers by messaging nearby units, sometimes in group
  chats. [Business Insider via AOL](https://www.aol.com/articles/ukraines-drone-operators-negotiate-safe-140113269.html)
- Soldiers who can't tell friend from foe "jam everything", hitting their own drones.
  [Business Insider via Yahoo](https://www.yahoo.com/news/soldiers-ukraine-panic-jam-everything-090501576.html)
- KSE lists "deconfliction tools that prevent friendly interference" as an EW opportunity.
  [KSE Institute, March 2026](https://institute.kse.ua/wp-content/uploads/2026/03/the-ukrainian_defense_technology_market_eng_march_2026.pdf)
- Ukrainian MoD training course on using EW without jamming friendly drones.
  [Mezha](https://mezha.net/eng/?p=1677424)
- US Army 2026 summit: airspace management raised by nearly every panel using UAS.
  [army.mil](https://www.army.mil/article/290518)

## Other existing systems

| System | Level | Gap vs Corridor |
|---|---|---|
| EWPMT (US Army) | Brigade EW officer, planning | Specialist tool, slow planning cycle. [source](https://www.mobilityengineeringtech.com/component/content/article/21934-innovative-army-tool-enhances-electronic-warfare-capabilities) |
| EMBM-J (DISA/STRATCOM) | Joint, spectrum situational awareness | Top level. [source](https://www.defensenews.com/electronic-warfare/2023/12/11/disa-launches-cloud-based-electronic-warfare-planning-tool/) |
| CJSMPT (DISA, older) | Blue-force RF conflict detection and resolution | Pre-mission planning, not real time. [source](https://webarchive.library.unt.edu/web/20161018234931/http://www.disa.mil/Mission-Support/Spectrum/GEMSIS/CJSMPT) |
| FAAD C2 (US Army) | Counter-UAS C2, friendly/enemy tracks | No jamming footprint, no routing. [source](https://dedrone.com/press/dedrone-completes-demonstration-of-faad-c2-integration-for-complete-airspace-security-for-u-s-army) |
| CMD3D / MARTHA (FR Army) | 3D airspace coordination incl. drones, 500 x 500 km | Air-defence level, procedural volumes. [source](https://www.defense.gouv.fr/terre/nos-materiels/nos-equipements-terre/nos-transmissions-informatique-radars/cmd3d-centre-management-defense-3e) |
| PARADE (FR, Thales + CS Group) | Site counter-UAS, open C2, civil UTM interop | Protects sites, does not route friendly drones. [source](https://www.thalesgroup.com/fr/actualites-du-groupe/communiques-de-presse/thales-et-cs-group-notifies-par-la-dga-pour-la-lutte) |
| NATO SMADEF-XML / ARCADE / SMIR | Frequency assignment | Spectrum admin, not tactical. [source](https://bilgem.tubitak.gov.tr/en/?p=103752) |

Line for the pitch: these work at brigade level or above, plan ahead of time, or track drones
without modelling jamming. None works pilot-to-jammer, minute by minute.
Possible export formats later: CoT (done), SMADEF-XML (NATO spectrum).

## TAK access facts

- ATAK-CIV: free on Google Play, source public on
  [GitHub](https://github.com/deptofdefense/AndroidTacticalAssaultKit-CIV). Current line 5.8
  ([plugin builds for 5.6 to 5.8](https://github.com/RyanR3/SARTAK/releases)).
- Official SDK on tak.gov requires a government sponsor ([FAQ](https://tak.gov/faq)); tak.gov is
  reported US-IP only. The public GitHub SDK is old (4.x).
- Play Store ATAK only loads plugins signed with a whitelisted key
  ([atak-forwarder README](https://github.com/paulmandal/atak-forwarder)): another reason for
  the external-service approach.
- WinTAK: latest public CIV build 5.5.0.155, in long-term sustainment
  ([COTAK forum](https://forum.cotak.gov/post/122)); successor is TAKX ([tak.gov](https://tak.gov/products)).
  Use an Android phone for the demo.
