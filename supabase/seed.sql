-- Starting categories. Keep catchment_k in sync with services/api/engine/config/scoring.yaml.
-- The pilot area itself is loaded from the owner's GeoJSON with:
--   uv run engine area load --slug pilot --name "<locality>" --geojson data/pilot_boundary.geojson

insert into public.categories (slug, name, description, osm_tags, google_types, google_text_query, catchment_k, sort_order)
values
  ('pharmacy', 'Pharmacy', 'Chemists and medical stores',
   '[{"amenity":"pharmacy"},{"shop":"chemist"},{"healthcare":"pharmacy"}]',
   '{pharmacy,drugstore}', null, 3, 10),
  ('cafe', 'Café or tea stall', 'Cafés, tea stalls and coffee shops',
   '[{"amenity":"cafe"},{"shop":"tea"},{"shop":"coffee"}]',
   '{cafe,coffee_shop,tea_house}', null, 2, 20),
  ('salon', 'Salon or barber', 'Hair salons, barbers and beauty parlours',
   '[{"shop":"hairdresser"},{"shop":"beauty"},{"shop":"barber"}]',
   '{hair_salon,beauty_salon,barber_shop}', null, 3, 30),
  ('coaching', 'Coaching centre', 'Tuition and coaching centres',
   '[{"amenity":"prep_school"},{"amenity":"tutoring"},{"amenity":"training"},{"office":"tutoring"},{"office":"educational_institution"}]',
   '{}', 'coaching centre', 6, 40),
  ('hardware', 'Hardware store', 'Hardware, paint and building supplies',
   '[{"shop":"hardware"},{"shop":"doityourself"},{"shop":"paint"},{"shop":"trade"}]',
   '{hardware_store,home_improvement_store}', null, 5, 50)
on conflict (slug) do update set
  name = excluded.name, description = excluded.description, osm_tags = excluded.osm_tags,
  google_types = excluded.google_types, google_text_query = excluded.google_text_query,
  catchment_k = excluded.catchment_k, sort_order = excluded.sort_order;
