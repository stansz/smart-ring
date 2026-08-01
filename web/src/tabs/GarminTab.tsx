import { useState } from "react";
import { GarminUpload } from "../components/garmin/GarminUpload";
import { ActivitiesList } from "../components/garmin/ActivitiesList";
import { ActivityDetail } from "../components/garmin/ActivityDetail";

/**
 * Garmin tab: browse 745 activity data ingested via USB.
 *
 * Layout:
 *   - Upload zone (top) — select the Garmin/ folder from the watch's USB drive
 *   - Activity list (filterable table)
 *   - Activity detail (HR chart + lap splits for the selected activity)
 *
 * On mobile, the list and detail stack; selecting an activity from the
 * list scrolls to the detail.
 */
export function GarminTab() {
  const [selectedId, setSelectedId] = useState<number | null>(null);

  return (
    <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      <GarminUpload />
      <ActivitiesList
        selectedId={selectedId}
        onSelect={setSelectedId}
      />
      {selectedId !== null && (
        <div className="mt-8">
          <ActivityDetail id={selectedId} />
        </div>
      )}
    </main>
  );
}
