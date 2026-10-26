// Mock data for the card-flow prototype. Streets come from data/streets.json, suburbs and
// postcodes are real, every number is made up. L-0001 to L-0005 mirror src/voice/mock_matrix.json;
// the other 45 are generated from a fixed seed so every reload shows the same 50. No demographics.

const N_LISTINGS = 50;

const STREETS = [
  'Alder Lane', 'Birchwood Street', 'Caldera Avenue', 'Dunmore Row', 'Ellery Place',
  'Fenwick Street', 'Glasshouse Lane', 'Harrow Crescent', 'Ingram Street', 'Juniper Avenue',
  'Kestrel Lane', 'Larkspur Street', 'Marlow Place', 'Norwood Lane', 'Orrin Street',
  'Pemberton Row', 'Quarry Lane', 'Rosslyn Avenue', 'Saltbush Street', 'Thornbury Lane',
];

const SUBURBS = {
  Kensington: '2033', Kingsford: '2032', Zetland: '2017',
  Haymarket: '2000', Randwick: '2031', Mascot: '2020',
};

// AM-peak minutes from each suburb to the three places people name most.
const HUB_TIMES = {
  Kensington: { central: [18, 'bus then train'], unsw: [9, 'walking'], cbd: [26, 'bus'] },
  Kingsford: { central: [24, 'light rail'], unsw: [12, 'walking'], cbd: [30, 'light rail'] },
  Zetland: { central: [14, 'bus'], unsw: [20, 'bus'], cbd: [19, 'bus'] },
  Haymarket: { central: [6, 'walking'], unsw: [25, 'light rail'], cbd: [9, 'walking'] },
  Randwick: { central: [26, 'light rail'], unsw: [8, 'walking'], cbd: [32, 'light rail'] },
  Mascot: { central: [12, 'train'], unsw: [27, 'bus'], cbd: [16, 'train'] },
};

// Weekly rent medians by bedrooms (1, 2, 3+), standing in for the DCJ table.
const MEDIAN = {
  Haymarket: [720, 1050, 1450], Zetland: [680, 920, 1250], Mascot: [600, 820, 1100],
  Kensington: [620, 840, 1150], Kingsford: [580, 790, 1050], Randwick: [610, 830, 1180],
};

const SOURCES = [
  { label: 'Listing pages', rows: 50 },
  { label: 'Floor plans + photo facts', rows: 412 },
  { label: 'Inspection reports + by-laws', rows: 61 },
  { label: 'Rent medians (DCJ)', rows: 96 },
  { label: 'Transit times, AM peak', rows: 300 },
  { label: 'Road noise + venues', rows: 180 },
];

// s = status, v = short value, src = label shown on screen, tb = Zetaris table,
// q = what the material says, why = how we got from q to s, proof = phrase for "the only one where ..."
function F(s, v, src, tb, q, why = '', proof = '') { return { s, v, src, tb, q, why, proof }; }

function commute(suburb, jitter = [0, 0, 0]) {
  const h = HUB_TIMES[suburb];
  return {
    central: { min: h.central[0] + jitter[0], mode: h.central[1] },
    unsw: { min: h.unsw[0] + jitter[1], mode: h.unsw[1] },
    cbd: { min: h.cbd[0] + jitter[2], mode: h.cbd[1] },
  };
}

const RICH = [
  {
    id: 'L-0001', unit: '7', street: '12 Alder Lane', suburb: 'Kensington', rent: 760, bed: 2, bath: 1, car: 1,
    avail: '2026-11-10', floor: 2, tint: 0, balcony: true, compass: true, north: 20,
    commute: { central: { min: 18, mode: 'bus then train' }, unsw: { min: 9, mode: 'walking' }, cbd: { min: 26, mode: 'bus' } },
    planNote: 'Floor plan: two bedrooms drawn, both with windows',
    special: 'Water usage is included in the rent.',
    f: {
      J1: F('inferred', 'by-laws silent', 'BY-LAWS', 'documents', 'By-laws excerpt: no clause on animals. No agent reply about pets on file.',
        'Nothing forbids pets and NSW rules only allow refusal on set grounds, so it leans yes. Nobody has confirmed it.'),
      C1: F('inferred', 'split system, room unclear', 'FLOOR PLAN', 'photo_facts',
        "Listing: 'Split system air conditioning'. Plan: AC symbol in the living room only. Inspection report: bedrooms not mentioned.",
        'Probably the living room only.'),
      E4: F('inferred', 'side street, bus route near', 'NOISE MAP', 'public_noise', 'Road noise class 2; bus route 60 m away',
        'A quiet street, but a bus route runs close.'),
      E2: F('inferred', 'north-east living, level 2', 'FLOOR PLAN', 'photo_facts', 'Compass on plan: living room faces north-east; level 2 of 4',
        'A north-east aspect on a low floor: likely morning sun, not confirmed.'),
      C2: F('conflict', 'unfurnished', 'LISTING', 'listings', "Listing: 'Unfurnished'", 'The listing says unfurnished.'),
      P1: F('supported', '1 car space', 'LISTING', 'listings', "Listing: '2 bed, 1 bath, 1 car'", '', 'the listing includes a car space'),
    },
  },
  {
    id: 'L-0002', unit: '12', street: '31 Fenwick Street', suburb: 'Zetland', rent: 890, bed: 2, bath: 2, car: 1,
    avail: '2026-11-01', floor: 6, tint: 2, balcony: true, compass: false,
    commute: { central: { min: 14, mode: 'bus' }, unsw: { min: 16, mode: 'bus' }, cbd: { min: 20, mode: 'bus' } },
    special: 'Two bathrooms, and an inspection report on file.',
    f: {
      J1: F('supported', 'allowed with consent', 'BY-LAWS', 'documents',
        "By-law 14: 'An owner or occupier may keep an animal with the written consent of the owners corporation, which must not be unreasonably withheld'",
        'The by-laws allow pets with consent that cannot be unreasonably withheld.', 'the by-laws allow pets'),
      C1: F('supported', 'vents in both bedrooms', 'INSPECTION', 'documents',
        "Inspection report: 'Ducted AC, vents in living, bed 1 and bed 2; ran cold on test'", '',
        'an inspection report confirms air con vents in both bedrooms'),
      E4: F('conflict', 'fronts a main road', 'NOISE MAP', 'public_noise', 'Road noise class 4: fronts Joynton Avenue',
        'The noise map puts the building on a busy road.'),
      E2: F('unknown', 'no compass on plan', '—', 'photo_facts', 'Floor plan has no north arrow', 'Without a compass the aspect cannot be read.'),
      C2: F('unknown', 'furniture in photos only', 'PHOTOS', 'photo_facts', 'Photos show a sofa and bed; no inventory on file',
        'Furniture in photos may belong to the last tenant.'),
      P1: F('supported', '1 car space', 'LISTING', 'listings', "Listing: '2 bed, 2 bath, 1 car'", '', 'the listing includes a car space'),
    },
  },
  {
    id: 'L-0003', unit: '3', street: '2 Harrow Crescent', suburb: 'Kingsford', rent: 700, bed: 2, bath: 1, car: 0,
    avail: '2026-11-24', floor: 1, tint: 1, balcony: false, compass: true, north: -35,
    commute: { central: { min: 24, mode: 'light rail' }, unsw: { min: 7, mode: 'walking' }, cbd: { min: 30, mode: 'light rail' } },
    special: 'The cheapest two-bed here, but the pet line needs a proper answer.',
    f: {
      J1: F('conflict', 'listing says no pets', 'LISTING', 'listings', "Listing: 'No pets'. By-laws excerpt: no clause on animals.",
        'The listing says no pets, but the by-laws are silent and NSW rules need set grounds to refuse. The listing line alone does not settle it.'),
      C1: F('unknown', 'not mentioned', '—', 'listings', 'Listing, plan and inspection report: no air con mentioned', 'Nothing mentions air con.'),
      E4: F('supported', 'quiet cul-de-sac', 'NOISE MAP', 'public_noise', 'Road noise class 1: cul-de-sac, no venues within 300 m', '',
        'the noise map puts it on a quiet cul-de-sac'),
      E2: F('inferred', 'north-west living, level 1', 'FLOOR PLAN', 'photo_facts', 'Compass on plan: living room faces north-west; ground-floor neighbour block 8 m away',
        'North-west helps, but the block opposite may shade it.'),
      C2: F('unknown', 'furniture in photos only', 'PHOTOS', 'photo_facts', 'Photos show a dining table; no inventory on file', 'Furniture in photos may not stay.'),
      P1: F('conflict', 'no parking listed', 'LISTING', 'listings', "Listing: 'Street parking only'", 'The listing says street parking only.'),
    },
  },
  {
    id: 'L-0004', unit: '9', street: '18 Marlow Place', suburb: 'Randwick', rent: 650, bed: 1, bath: 1, car: 0,
    avail: '2026-11-05', floor: 3, tint: 3, balcony: true, compass: true, north: 0,
    commute: { central: { min: 22, mode: 'bus' }, unsw: { min: 12, mode: 'bus' }, cbd: { min: 28, mode: 'bus' } },
    special: 'A one-bedroom, so it only comes up when one bedroom is enough.',
    f: {
      J1: F('inferred', 'by-laws silent', 'BY-LAWS', 'documents', 'By-laws excerpt: no clause on animals', 'Nothing forbids pets; nobody has asked the agent.'),
      C1: F('unknown', 'not mentioned', '—', 'listings', 'Listing: no air con listed', 'Nothing mentions air con.'),
      E4: F('inferred', 'moderate traffic', 'NOISE MAP', 'public_noise', 'Road noise class 3', 'Some traffic noise is likely.'),
      E2: F('inferred', 'north-facing, level 3', 'FLOOR PLAN', 'photo_facts', 'Compass on plan: living room faces north; level 3 of 5',
        'North-facing on level 3: likely good sun, not confirmed.'),
      C2: F('supported', 'furnished per inventory', 'INVENTORY', 'documents', 'Inventory: bed, sofa, desk, fridge, washing machine', '',
        'the inventory lists furniture'),
      P1: F('conflict', 'no parking listed', 'LISTING', 'listings', "Listing: 'No parking'", 'The listing says no parking.'),
    },
  },
  {
    id: 'L-0005', unit: '5', street: '44 Juniper Avenue', suburb: 'Zetland', rent: 980, bed: 2, bath: 2, car: 1,
    avail: '2026-11-15', floor: 8, tint: 4, balcony: true, compass: true, north: 160,
    commute: { central: { min: 15, mode: 'bus' }, unsw: { min: 18, mode: 'bus' }, cbd: { min: 21, mode: 'bus' } },
    special: 'Has everything, but sits above most budgets.',
    f: {
      J1: F('supported', 'allowed with consent', 'BY-LAWS', 'documents', 'By-law 12: pets with written consent', 'The by-laws allow pets with consent.', 'the by-laws allow pets'),
      C1: F('supported', 'split systems in both bedrooms', 'INSPECTION', 'documents', "Inspection report: 'Split systems in bed 1 and bed 2'", '',
        'an inspection report confirms air con in both bedrooms'),
      E4: F('inferred', 'moderate traffic', 'NOISE MAP', 'public_noise', 'Road noise class 3', 'Some traffic noise is likely.'),
      E2: F('inferred', 'north-facing, level 8', 'FLOOR PLAN', 'photo_facts', 'Compass on plan: living room faces north; level 8 of 12',
        'High floor facing north: likely strong sun, not confirmed.'),
      C2: F('unknown', 'furniture in photos only', 'PHOTOS', 'photo_facts', "Photos carry a 'virtual staging' watermark", 'Staged photos do not count as furniture.'),
      P1: F('supported', '1 car space', 'LISTING', 'listings', "Listing: '2 bed, 2 bath, 1 car'", '', 'the listing includes a car space'),
    },
  },
];

function seeded(seed) {
  let s = seed >>> 0 || 1;
  return () => { s ^= s << 13; s >>>= 0; s ^= s >>> 17; s ^= s << 5; s >>>= 0; return s / 4294967296; };
}

function weighted(r, table) {
  let x = r();
  for (const [p, v] of table) { if ((x -= p) <= 0) return v; }
  return table[table.length - 1][1];
}

function addDays(iso, n) {
  const d = new Date(iso + 'T00:00:00Z');
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

function generateListings() {
  const r = seeded(20261025);
  const subs = Object.keys(SUBURBS);
  const out = [];
  for (let i = 6; i <= N_LISTINGS; i++) {
    const suburb = subs[Math.floor(r() * subs.length)];
    const bed = weighted(r, [[0.32, 1], [0.46, 2], [0.22, 3]]);
    const bath = bed === 1 ? 1 : bed === 3 ? (r() < 0.8 ? 2 : 1) : (r() < 0.45 ? 2 : 1);
    const base = MEDIAN[suburb][bed - 1];
    const rent = Math.round(base * (0.86 + r() * 0.36) / 10) * 10;
    const car = r() < (bed === 1 ? 0.3 : 0.62) ? 1 : 0;
    const floor = 1 + Math.floor(r() * 9);
    const compass = r() < 0.7;
    const north = Math.round(r() * 360);
    const facing = ['north', 'north-east', 'east', 'south-east', 'south', 'south-west', 'west', 'north-west'][Math.floor(r() * 8)];
    const noise = 1 + Math.floor(r() * 5);
    const id = 'L-' + String(i).padStart(4, '0');
    const f = {};
    f.J1 = weighted(r, [
      [0.16, F('supported', 'allowed with consent', 'BY-LAWS', 'documents', 'By-law: animals allowed with written consent of the owners corporation',
        'The by-laws allow pets with consent.', 'the by-laws allow pets')],
      [0.30, F('inferred', 'by-laws silent', 'BY-LAWS', 'documents', 'By-laws excerpt: no clause on animals',
        'Nothing forbids pets and NSW rules limit refusals, so it leans yes. Nobody has confirmed it.')],
      [0.18, F('conflict', 'listing says no pets', 'LISTING', 'listings', "Listing: 'No pets'",
        'The listing says no pets; under NSW rules that line alone does not settle it.')],
      [0.36, F('unknown', 'nothing on file', '—', 'documents', 'No by-laws or agent reply on file', 'No material mentions pets.')],
    ]);
    f.C1 = weighted(r, [
      [0.14, F('supported', 'AC in both bedrooms', 'INSPECTION', 'documents', "Inspection report: 'Split systems in bed 1 and bed 2'", '',
        'an inspection report confirms air con in the bedrooms')],
      [0.30, F('inferred', 'AC listed, room unclear', 'LISTING', 'listings', "Listing features: 'Air conditioning'",
        'The listing ticks air con for the property, which says nothing about the bedrooms.')],
      [0.16, F('conflict', 'living room only', 'FLOOR PLAN', 'photo_facts', 'Floor plan: AC symbol in the living room only',
        'The plan shows the only unit in the living room.')],
      [0.40, F('unknown', 'not mentioned', '—', 'listings', 'No material mentions air con', 'Nothing mentions air con.')],
    ]);
    f.E4 = noise <= 2
      ? F('supported', 'quiet side street', 'NOISE MAP', 'public_noise', `Road noise class ${noise}; no venues within 200 m`, '', 'the noise map puts it on a quiet side street')
      : noise === 3
        ? F('inferred', 'moderate traffic', 'NOISE MAP', 'public_noise', 'Road noise class 3', 'Some traffic noise is likely.')
        : F('conflict', 'fronts a main road', 'NOISE MAP', 'public_noise', `Road noise class ${noise}: arterial road frontage`, 'The noise map puts it on a busy road.');
    if (!compass) f.E2 = F('unknown', 'no compass on plan', '—', 'photo_facts', 'Floor plan has no north arrow', 'Without a compass the aspect cannot be read.');
    else if (facing.startsWith('south')) f.E2 = F('conflict', `${facing}-facing living`, 'FLOOR PLAN', 'photo_facts', `Compass on plan: living room faces ${facing}`, 'A south aspect gets little direct sun.');
    else f.E2 = F('inferred', `${facing}-facing, level ${floor}`, 'FLOOR PLAN', 'photo_facts', `Compass on plan: living room faces ${facing}; level ${floor}`,
      'Aspect and floor suggest decent light; sun can only ever be inferred.');
    f.C2 = weighted(r, [
      [0.12, F('supported', 'furnished per inventory', 'INVENTORY', 'documents', 'Inventory: bed, sofa, table, fridge', '', 'the inventory lists furniture')],
      [0.38, F('conflict', 'unfurnished', 'LISTING', 'listings', "Listing: 'Unfurnished'", 'The listing says unfurnished.')],
      [0.50, F('unknown', 'furniture in photos only', 'PHOTOS', 'photo_facts', 'Photos show furniture; no inventory on file', 'Furniture in photos may not stay.')],
    ]);
    f.P1 = car
      ? F('supported', '1 car space', 'LISTING', 'listings', `Listing: '${bed} bed, ${bath} bath, 1 car'`, '', 'the listing includes a car space')
      : F('conflict', 'no parking listed', 'LISTING', 'listings', "Listing: 'Street parking only'", 'The listing says street parking only.');
    out.push({
      id, unit: String(1 + Math.floor(r() * 24)), street: `${2 + Math.floor(r() * 88)} ${STREETS[Math.floor(r() * STREETS.length)]}`,
      suburb, rent, bed, bath, car, avail: addDays('2026-10-27', Math.floor(r() * 55)), floor,
      tint: Math.floor(r() * 6), balcony: r() < 0.55, compass, north,
      commute: commute(suburb, [Math.floor(r() * 7) - 2, Math.floor(r() * 7) - 2, Math.floor(r() * 7) - 2]),
      special: '', f,
    });
  }
  return out;
}

const LISTINGS = [...RICH, ...generateListings()].map(l => ({ ...l, postcode: SUBURBS[l.suburb] }));
