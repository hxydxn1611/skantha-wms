import os

with open('webapp/ai_engine.py', 'r', encoding='utf-8') as f:
    code = f.read()

# 1. Remove the line drawing code
old_line_code = """        # Draw the Virtual Tripwire Line
        tripwire_y = self.tripwire_y
        cv2.line(display_frame, (0, tripwire_y), (display_frame.shape[1], tripwire_y), (0, 0, 255), 2)
        cv2.putText(display_frame, "COUNTING LINE", (10, tripwire_y - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)"""
        
new_line_code = """        # Virtual Tripwire Line removed dynamically as per user request"""

code = code.replace(old_line_code, new_line_code)

# 2. Update counting logic
old_logic = """                        # --- TRIPWIRE LOGIC FOR PACKAGE COUNTING ---
                        if track_id is not None:
                            cx = int((x1 + x2) / 2)
                            cy = int((y1 + y2) / 2)
                            
                            # If we've seen this box before, check if it crossed the line
                            if track_id in self.tracked_centroids:
                                prev_cy = self.tracked_centroids[track_id][1]
                                # Crossed from top to bottom
                                if prev_cy < self.tripwire_y and cy >= self.tripwire_y:
                                    if track_id not in self.seen_package_ids:
                                        self.seen_package_ids.add(track_id)"""

new_logic = """                        # --- OMNIDIRECTIONAL COUNTING LOGIC ---
                        if track_id is not None:
                            cx = int((x1 + x2) / 2)
                            cy = int((y1 + y2) / 2)
                            
                            if track_id in self.tracked_centroids:
                                # We count the item as soon as it is reliably tracked, regardless of orientation or line
                                if track_id not in self.seen_package_ids:
                                    self.seen_package_ids.add(track_id)"""
                                    
code = code.replace(old_logic, new_logic)

with open('webapp/ai_engine.py', 'w', encoding='utf-8') as f:
    f.write(code)

print("Removed tripwire and made counting omni-directional.")
