\* procurement *\
Maximize
OBJ: 829.5189141 y_ats_4 + 999.995103 y_ats_5 + 626.863157 y_ats_6
 + 999.9836992 y_kvm_7 + 571.3210832 y_kvm_8 + 999.9448762 y_pc_13
 + 710.2326861 y_pc_14 + 576.9229684 y_sw_10 + 999.9697871 y_sw_11
 + 582.8099712 y_sw_12 + 638.1890453 y_sw_9 + 443.0095714 y_ups_0
 + 470.269803 y_ups_1 + 863.1080292 y_ups_2 + 999.9826624 y_ups_3
Subject To
budget: 70858.7854569 y_ats_4 + 48969.9501176 y_ats_5 + 98429.6654742 y_ats_6
 + 163008.293131 y_kvm_7 + 179167.931951 y_kvm_8 + 551237.655781 y_pc_13
 + 463138.538003 y_pc_14 + 220316.336489 y_sw_10 + 302128.533099 y_sw_11
 + 100287.977324 y_sw_12 + 309546.748001 y_sw_9 + 774286.03027 y_ups_0
 + 241970.399428 y_ups_1 + 239707.527697 y_ups_2 + 173375.835365 y_ups_3
 <= 12000000
demand_ats: y_ats_4 + y_ats_5 + y_ats_6 = 10
demand_kvm: y_kvm_7 + y_kvm_8 = 10
demand_pc: y_pc_13 + y_pc_14 = 10
demand_sw: y_sw_10 + y_sw_11 + y_sw_12 + y_sw_9 = 10
demand_ups: y_ups_0 + y_ups_1 + y_ups_2 + y_ups_3 = 10
high_risk: y_pc_13 + y_pc_14 + y_sw_10 + y_sw_9 + y_ups_0 <= 15
lot_ats_4: y_ats_4 - 2 z_ats_4 >= 0
lot_ats_5: y_ats_5 - 2 z_ats_5 >= 0
lot_ats_6: y_ats_6 - 2 z_ats_6 >= 0
lot_kvm_7: y_kvm_7 - 2 z_kvm_7 >= 0
lot_kvm_8: y_kvm_8 - 2 z_kvm_8 >= 0
lot_pc_13: y_pc_13 - 2 z_pc_13 >= 0
lot_pc_14: y_pc_14 - 2 z_pc_14 >= 0
lot_sw_10: y_sw_10 - 2 z_sw_10 >= 0
lot_sw_11: y_sw_11 - 2 z_sw_11 >= 0
lot_sw_12: y_sw_12 - 2 z_sw_12 >= 0
lot_sw_9: y_sw_9 - 2 z_sw_9 >= 0
lot_ups_0: y_ups_0 - 2 z_ups_0 >= 0
lot_ups_1: y_ups_1 - 2 z_ups_1 >= 0
lot_ups_2: y_ups_2 - 2 z_ups_2 >= 0
lot_ups_3: y_ups_3 - 2 z_ups_3 >= 0
share_ats_4: y_ats_4 - 6 z_ats_4 <= 0
share_ats_5: y_ats_5 - 6 z_ats_5 <= 0
share_ats_6: y_ats_6 - 6 z_ats_6 <= 0
share_kvm_7: y_kvm_7 - 6 z_kvm_7 <= 0
share_kvm_8: y_kvm_8 - 6 z_kvm_8 <= 0
share_pc_13: y_pc_13 - 6 z_pc_13 <= 0
share_pc_14: y_pc_14 - 6 z_pc_14 <= 0
share_sw_10: y_sw_10 - 6 z_sw_10 <= 0
share_sw_11: y_sw_11 - 6 z_sw_11 <= 0
share_sw_12: y_sw_12 - 6 z_sw_12 <= 0
share_sw_9: y_sw_9 - 6 z_sw_9 <= 0
share_ups_0: y_ups_0 - 6 z_ups_0 <= 0
share_ups_1: y_ups_1 - 6 z_ups_1 <= 0
share_ups_2: y_ups_2 - 6 z_ups_2 <= 0
share_ups_3: y_ups_3 - 6 z_ups_3 <= 0
suppliers_ats: z_ats_4 + z_ats_5 + z_ats_6 <= 2
suppliers_kvm: z_kvm_7 + z_kvm_8 <= 2
suppliers_pc: z_pc_13 + z_pc_14 <= 2
suppliers_sw: z_sw_10 + z_sw_11 + z_sw_12 + z_sw_9 <= 2
suppliers_ups: z_ups_0 + z_ups_1 + z_ups_2 + z_ups_3 <= 2
Bounds
 0 <= y_ups_0 <= 10
 y_ups_1 = 0
 z_ups_1 = 0
 0 <= y_ups_2 <= 10
 0 <= y_ups_3 <= 10
 0 <= y_ats_4 <= 10
 0 <= y_ats_5 <= 10
 0 <= y_ats_6 <= 10
 0 <= y_kvm_7 <= 10
 0 <= y_kvm_8 <= 10
 0 <= y_sw_9 <= 10
 0 <= y_sw_10 <= 10
 0 <= y_sw_11 <= 10
 0 <= y_sw_12 <= 10
 0 <= y_pc_13 <= 10
 0 <= y_pc_14 <= 10
Generals
y_ups_0
y_ups_1
z_ups_1
y_ups_2
y_ups_3
y_ats_4
y_ats_5
y_ats_6
y_kvm_7
y_kvm_8
y_sw_9
y_sw_10
y_sw_11
y_sw_12
y_pc_13
y_pc_14
Binaries
z_ups_0
z_ups_2
z_ups_3
z_ats_4
z_ats_5
z_ats_6
z_kvm_7
z_kvm_8
z_sw_9
z_sw_10
z_sw_11
z_sw_12
z_pc_13
z_pc_14
End
