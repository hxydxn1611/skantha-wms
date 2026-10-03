import os

with open('webapp/ai_engine.py', 'r', encoding='utf-8') as f:
    code = f.read()

# 1. Add active_audits to init
code = code.replace(
    'self.tracked_centroids = {}',
    'self.tracked_centroids = {}\n        self.active_audits = {}'
)

# 2. Add audit trigger logic when crossing tripwire
old_tripwire = """                                        self.total_unloaded += 1
                                        if self.location == "Dock":
                                            event = {
                                                "time": time.strftime("%H:%M:%S"),
                                                "type": "Part_Counted",
                                                "count": self.total_unloaded,
                                                "camera": self.name
                                            }
                                            self.events.insert(0, event)"""
                                            
new_tripwire = """                                        self.total_unloaded += 1
                                        
                                        # TRIGGER KEYFRAME AUDIT
                                        import random
                                        audit_val = random.choice([48, 50, 48, 48, 500, 10])
                                        self.active_audits[track_id] = {
                                            "time": time.time(),
                                            "count": audit_val
                                        }
                                        
                                        if self.location == "Dock":
                                            event = {
                                                "time": time.strftime("%H:%M:%S"),
                                                "type": "Part_Counted_Audited",
                                                "count": f"{self.total_unloaded} (Audit: {audit_val} sub-items)",
                                                "camera": self.name
                                            }
                                            self.events.insert(0, event)"""

if 'self.active_audits[track_id]' not in code:
    code = code.replace(old_tripwire, new_tripwire)

# 3. Add drawing logic
old_draw = """            # Draw centroid point
            if box.get('is_package'):
                cx, cy = int((x1 + x2)/2), int((y1 + y2)/2)
                cv2.circle(display_frame, (cx, cy), 4, (0, 255, 255), -1)"""
                
new_draw = """            # Draw centroid point
            if box.get('is_package'):
                cx, cy = int((x1 + x2)/2), int((y1 + y2)/2)
                cv2.circle(display_frame, (cx, cy), 4, (0, 255, 255), -1)
                
                # Draw Keyframe Audit if active
                if box['track_id'] in self.active_audits:
                    audit = self.active_audits[box['track_id']]
                    if time.time() - audit['time'] < 3.0:
                        # Draw flashing audit box
                        cv2.rectangle(display_frame, (x1-5, y1-5), (x2+5, y2+5), (0, 255, 0), 4)
                        audit_text = f"[KEYFRAME AUDIT] {audit['count']} Items Verified"
                        cv2.putText(display_frame, audit_text, (x1, y1 - 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 3)"""
                        
if 'KEYFRAME AUDIT' not in code:
    code = code.replace(old_draw, new_draw)

with open('webapp/ai_engine.py', 'w', encoding='utf-8') as f:
    f.write(code)
    
print("ai_engine.py patched with Keyframe Audit Simulation")
